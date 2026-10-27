from contextlib import closing
import json

import pytest

from cctv_tracker.config import Settings
from cctv_tracker.fleet import CameraFleet, FairDetector
from cctv_tracker.lease import EngineLease
from cctv_tracker.maintenance import BackupManager, app_lock_path
from cctv_tracker.persistence import Database
from test_live import FixtureDetector
from test_fleet import Capture, setup_camera


def test_backup_verifies_reid_migration_and_accepts_previous_release(tmp_path, monkeypatch):
    import cctv_tracker.persistence as persistence
    from cctv_tracker.maintenance import verify_database
    path = tmp_path / 'previous.sqlite3'
    with monkeypatch.context() as previous:
        previous.setattr(persistence, 'MIGRATION_FILES', persistence.MIGRATION_FILES[:4])
        with closing(Database(path)):
            pass
    verify_database(path)
    with closing(Database(path)) as db:
        assert db.conn.execute('PRAGMA user_version').fetchone()[0] == 5
    verify_database(path)
    with closing(Database(path)) as db:
        db.conn.execute("UPDATE runtime_migration_checksums SET sha256=? WHERE version=5", ('0' * 64,))
        db.conn.commit()
    with pytest.raises(ValueError, match='migration checksum'):
        verify_database(path)


def test_verified_round_trip_includes_config_and_refuses_running_app(tmp_path):
    path = tmp_path / 'site.sqlite3'
    with closing(Database(path)) as db:
        original = db.add_employee('Before backup')
    fleet = CameraFleet(Settings(database=path), FairDetector(FixtureDetector()), capture_factory=Capture)
    camera = setup_camera(fleet, 'north')
    manager = BackupManager(path, fleet)
    manifest = manager.create()
    fleet.shutdown()
    manager.fleet = None
    assert len(manifest['files']) == 3
    with closing(Database(path)) as db:
        db.add_employee('After backup')
    lease = EngineLease(app_lock_path(path))
    try:
        with pytest.raises(RuntimeError, match='Another occupancy writer'):
            manager.restore(manifest['id'])
    finally:
        lease.close()
    receipt = manager.restore(manifest['id'])
    assert receipt['verified'] and receipt['safety_backup_id'] != manifest['id']
    with closing(Database(path)) as db:
        assert [r['id'] for r in db.conn.execute('SELECT id FROM employees')] == [original]
    reloaded = CameraFleet(Settings(database=path), FixtureDetector(), capture_factory=Capture)
    try:
        assert reloaded.get(camera).engine.profiles['RTSP_LIVE']['revision'] == 1
    finally:
        reloaded.shutdown()
    assert manager.status()['restore_receipt']['verified']
    assert not manager.journal.exists()


def test_tamper_path_rejection_and_partial_restore_resume(tmp_path, monkeypatch):
    path = tmp_path / 'site.sqlite3'
    with closing(Database(path)) as db:
        db.add_employee('Saved')
    manager = BackupManager(path)
    snapshot = manager.create()
    with pytest.raises(ValueError):
        manager.verify('../other')
    with pytest.raises(ValueError):
        manager.target('fleet/../outside')
    backup = manager.root / snapshot['id'] / 'replay.sqlite3'
    content = backup.read_bytes()
    backup.write_bytes(b'invalid')
    with pytest.raises(ValueError, match='checksum'):
        manager.restore(snapshot['id'])
    assert not manager.journal.exists()

    backup.write_bytes(content)
    import cctv_tracker.maintenance as module
    write = module.atomic_write
    def fail_receipt(target, data):
        if target == manager.receipt:
            raise OSError('injected crash after database restore')
        write(target, data)
    monkeypatch.setattr(module, 'atomic_write', fail_receipt)
    with pytest.raises(OSError):
        manager.restore(snapshot['id'])
    assert manager.journal.exists()
    safety = json.loads(manager.journal.read_text())['safety_backup_id']
    monkeypatch.setattr(module, 'atomic_write', write)
    assert manager.restore(snapshot['id'])['safety_backup_id'] == safety
    assert not manager.journal.exists()

def test_restore_recording_policy_and_disable_when_backup_predates_it(tmp_path):
    from cctv_tracker.records import DEFAULT_POLICY, RecordingManager
    path = tmp_path / 'site.sqlite3'
    with closing(Database(path)):
        pass
    backup = BackupManager(path)
    before_policy = backup.create()
    recorder = RecordingManager(path)
    enabled = {**DEFAULT_POLICY, 'video_enabled': True, 'data_enabled': True, 'video_segment_seconds': 5}
    recorder.configure(enabled)
    after_policy = backup.create()
    assert 'recording-policy.json' in after_policy['files']
    recorder.configure(DEFAULT_POLICY)
    backup.restore(after_policy['id'])
    assert RecordingManager(path).policy == enabled
    backup.restore(before_policy['id'])
    assert RecordingManager(path).policy == DEFAULT_POLICY


def test_backup_restores_protected_upload_destination_and_old_backup_disables_it(tmp_path):
    from cctv_tracker.records import RecordingManager
    from cctv_tracker.record_destinations import DEFAULT_DESTINATION
    path = tmp_path / 'site.sqlite3'
    with closing(Database(path)):
        pass
    manager = RecordingManager(path)
    backup = BackupManager(path)
    before = backup.create()
    configured = {**DEFAULT_DESTINATION,'kind':'s3','enabled':False,'endpoint':'https://example.invalid','bucket':'records',
                  'access_key':'backup-fixture-access','secret_key':'backup-fixture-secret'}
    manager.destinations.configure(configured)
    after = backup.create()
    assert 'record-destination.protected' in after['files']
    assert b'backup-fixture-secret' not in (backup.root/after['id']/'record-destination.protected').read_bytes()
    manager.destinations.configure(DEFAULT_DESTINATION)
    backup.restore(after['id'])
    restored = RecordingManager(path)
    assert restored.destinations.config['secret_key'] == 'backup-fixture-secret'
    backup.restore(before['id'])
    assert RecordingManager(path).destinations.config == DEFAULT_DESTINATION
