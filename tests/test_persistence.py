from contextlib import closing
from dataclasses import replace
from pathlib import Path
import sqlite3
import pytest

from cctv_tracker.config import load_settings, timestamp
from cctv_tracker.persistence import Database
from cctv_tracker.pipeline import replay

ROOT = Path(__file__).resolve().parents[1]


def settings(path):
    return replace(load_settings(ROOT / "config/pilot.example.json"), database=path)


def test_migration_is_repeatable_and_resources_unchanged(tmp_path):
    path = tmp_path / "tracker.sqlite3"
    for _ in range(2):
        with closing(Database(path)) as db:
            assert db.conn.execute("PRAGMA user_version").fetchone()[0] == 5
            assert db.conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
            assert db.conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
            assert db.conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == 5
            assert db.conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_newer_schema_and_unversioned_database_refused(tmp_path):
    path = tmp_path / "new.sqlite3"
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA user_version=99")
    conn.close()
    with pytest.raises(ValueError, match="newer"):
        Database(path)
    other = tmp_path / "old.sqlite3"
    conn = sqlite3.connect(other)
    conn.execute("CREATE TABLE manual(x)")
    conn.close()
    with pytest.raises(ValueError, match="unversioned"):
        Database(other)


def test_upgrade_v2_preserves_existing_data_and_checksums(tmp_path):
    path = tmp_path / 'upgrade.sqlite3'
    with closing(Database(path)) as db:
        employee = db.add_employee('Migration fixture')
        with db.transaction() as conn:
            # Recreate an existing v2 database using only this disposable fixture.
            conn.execute('DROP TABLE live_calibrations')
            conn.execute('DROP TABLE reid_decisions')
            conn.execute('DROP TABLE person_sessions')
            conn.execute('DELETE FROM runtime_migration_checksums WHERE version>=3')
            conn.execute('DELETE FROM schema_migrations WHERE version>=3')
            conn.execute('PRAGMA user_version=2')
    with closing(Database(path)) as db:
        assert db.conn.execute('PRAGMA user_version').fetchone()[0] == 5
        assert db.conn.execute('SELECT display_name FROM employees WHERE id=?', (employee,)).fetchone()[0] == 'Migration fixture'
        assert db.conn.execute('SELECT COUNT(*) FROM runtime_migration_checksums').fetchone()[0] == 5


def test_same_model_weights_retain_different_execution_runtime_per_run(tmp_path):
    import json
    config = settings(tmp_path / 'runtime-provenance.sqlite3')
    with closing(Database(config.database)) as db:
        first = db.begin_run(config, source='WEBCAM_LIVE', model_sha='a' * 64, model_manifest={'provider': 'CPUExecutionProvider'}, start=1_000_000)
        first.finish(1_000_000, 'STOPPED')
        second = db.begin_run(config, source='WEBCAM_LIVE', model_sha='a' * 64, model_manifest={'provider': 'OpenVINO', 'execution_devices': ['GPU.0'], 'precision': 'f32'}, start=2_000_000)
        second.finish(2_000_000, 'STOPPED')
        rows = [json.loads(r[0]) for r in db.conn.execute('SELECT runtime_manifest_json FROM engine_runs ORDER BY started_utc_us')]
        assert rows[0]['inference_runtime']['provider'] == 'CPUExecutionProvider'
        assert rows[1]['inference_runtime']['provider'] == 'OpenVINO'
        assert rows[1]['inference_runtime']['execution_devices'] == ['GPU.0']
        assert db.conn.execute('SELECT COUNT(*) FROM model_artifacts').fetchone()[0] == 1


def test_replay_sqlite_golden_totals_and_atomic_durability(tmp_path):
    config = settings(tmp_path / "replay.sqlite3")
    with closing(Database(config.database)) as db:
        result = replay(ROOT / "tests/fixtures/occupancy-replay.json", config, db)
        assert result["data_sources"] == ["SYNTHETIC_REPLAY"]
        first, second = result["workstations"]
        # The 0.2 s before the first contradictory frame is unknown, not occupied.
        assert first["occupied_us"] == 3_800_000
        assert first["empty_us"] == 1_800_000
        assert first["unknown_us"] == 11_400_000
        assert first["eligible_us"] == 17_000_000
        import json
        metadata=json.loads(db.conn.execute('SELECT runtime_manifest_json FROM engine_runs').fetchone()[0])
        assert metadata['evidence_policy_revision']=='last-supporting-sample-v2'
        assert second["empty_us"] == 6_000_000
        assert second["unknown_us"] == 11_000_000
        assert db.conn.execute("SELECT COUNT(*) FROM occupied_sessions WHERE workspace_id=?", (first["workspace_id"],)).fetchone()[0] == 2
        assert db.conn.execute("SELECT COUNT(*) FROM zone_intervals WHERE end_utc_us IS NULL").fetchone()[0] == 0
        assert db.conn.execute("PRAGMA foreign_key_check").fetchall() == []
        with pytest.raises(RuntimeError):
            with db.transaction() as conn:
                conn.execute("INSERT INTO employees VALUES('rollback','Test',1,1)")
                raise RuntimeError("Injected failure")
        assert db.conn.execute("SELECT COUNT(*) FROM employees").fetchone()[0] == 0
    with closing(Database(config.database)) as db:
        assert db.report(result["start_utc_us"], result["end_utc_us"])["workstations"] == result["workstations"]


def test_assignment_has_effective_time_and_never_becomes_observed_identity(tmp_path):
    config = settings(tmp_path / "assignment.sqlite3")
    with closing(Database(config.database)) as db:
        result = replay(ROOT / "tests/fixtures/occupancy-replay.json", config, db)
        workspace = result["workstations"][0]["workspace_id"]
        employee = db.add_employee("Karyawan Contoh")
        start, end = result["start_utc_us"], result["end_utc_us"]
        db.assign(employee, workspace, start, start + 5_000_000)
        with pytest.raises(sqlite3.IntegrityError, match="overlapping"):
            db.assign(employee, workspace, start + 1, end)
        row = db.report(start, end)["workstations"][0]
        assert row["identity_source"] == "anonymous"
        assert row["observed_employee_id"] is None
        assert row["assignment_is_observed_identity"] is False
        assert row["workstation_assignments"][0]["source"] == "manual_assignment"
        assert not db.report(start + 6_000_000, end)["workstations"][0]["workstation_assignments"]


def test_migration_checksum_detects_tampering(tmp_path):
    path = tmp_path / "checksum.sqlite3"
    with closing(Database(path)) as db:
        with db.transaction() as conn:
            conn.execute("UPDATE runtime_migration_checksums SET sha256=? WHERE version=1", ("0" * 64,))
    with pytest.raises(ValueError, match="differs"):
        Database(path)


def test_process_restart_does_not_extend_last_occupied_state(tmp_path):
    from cctv_tracker.pipeline import Pipeline
    from cctv_tracker.vision import Detection
    path = tmp_path / "recovery.sqlite3"
    config = settings(path)
    start = timestamp("2026-10-12T09:00:00+07:00")
    db = Database(path)
    first = Pipeline(config, db, start, "SYNTHETIC_REPLAY", "1" * 64, {},)
    detections = [Detection((0.1, 0.2, 0.3, 0.8), 0.95)]
    for i in range(21):
        first.feed(detections, start + i * 200_000, i * 200_000_000, i + 1, "g1")
    first_id = first.writer.run_id
    # Crash simulation: release resources without the normal finish transaction.
    first.lease.close()
    db.close()
    with closing(Database(path)) as recovered:
        second = Pipeline(config, recovered, start + 10_000_000, "SYNTHETIC_REPLAY", "1" * 64, {})
        for i in range(21):
            second.feed(detections, start + 10_000_000 + i * 200_000, (50 + i) * 200_000_000, i + 1, "g1")
        second.finish()
        row = recovered.report(start, start + 14_000_000)["workstations"][0]
        assert row["occupied_us"] == 4_000_000
        assert row["unknown_us"] == 10_000_000
        assert recovered.conn.execute("SELECT termination_reason FROM engine_runs WHERE id=?", (first_id,)).fetchone()[0] == "INTERRUPTED"
        ids = [r[0] for r in recovered.conn.execute("SELECT DISTINCT track_id FROM track_visits")]
        assert len(ids) == 2


def test_second_process_cannot_acquire_writer_lease(tmp_path):
    import subprocess
    import sys
    from cctv_tracker.lease import EngineLease
    path = tmp_path / "lease.sqlite3"
    first = EngineLease(path)
    try:
        code = "from pathlib import Path; from cctv_tracker.lease import EngineLease; EngineLease(Path(__import__('sys').argv[1]))"
        result = subprocess.run([sys.executable, "-c", code, str(path)], capture_output=True, text=True)
        assert result.returncode != 0
        assert "already owns" in result.stderr
    finally:
        first.close()
    second = EngineLease(path)
    second.close()
