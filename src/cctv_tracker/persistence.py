from contextlib import contextmanager
from datetime import datetime, timezone
from importlib.resources import files
from pathlib import Path
from dataclasses import asdict
from uuid import uuid4, uuid5, NAMESPACE_URL
import hashlib
import json
import sqlite3
import threading

from .domain.occupancy import Interval, State, summarize


def now_us():
    return int(datetime.now(timezone.utc).timestamp() * 1_000_000)


def stable_id(value):
    return str(uuid5(NAMESPACE_URL, "cctv-tracker:" + value))


class Database:
    """One owning thread; synchronous commits define the durable watermark."""

    def __init__(self, path: Path, *, migrate=True):
        self.owner = threading.get_ident()
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path, timeout=5)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.execute("PRAGMA busy_timeout=5000")
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=FULL")
        try:
            if migrate:
                self.migrate()
        except BaseException:
            self.conn.close()
            raise

    def close(self):
        self.conn.close()

    @contextmanager
    def transaction(self):
        if threading.get_ident() != self.owner:
            raise RuntimeError("Database mutation attempted from another thread")
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            yield self.conn
            self.conn.commit()
        except BaseException:
            self.conn.rollback()
            raise

    def migrate(self):
        scripts = [files("cctv_tracker").joinpath("resources", name).read_text(encoding="utf-8")
                   for name in ("001_initial.sql", "002_assignments.sql", "003_live.sql", "004_person_sessions.sql")]
        version = self.conn.execute("PRAGMA user_version").fetchone()[0]
        if version > len(scripts):
            raise ValueError("Database schema is newer than this application")
        tables = self.conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        if version == 0 and tables:
            raise ValueError("Refusing an unversioned database; import requires a separate migration")
        for index, script in enumerate(scripts, start=1):
            if index <= version:
                continue
            body = script.replace("BEGIN;", "").replace("COMMIT;", "")
            checksum = hashlib.sha256(script.encode()).hexdigest()
            suffix = f"INSERT INTO schema_migrations VALUES({index},'runtime migration {index}',{now_us()});"
            if index == 1:
                suffix += f"INSERT INTO database_state VALUES(1,'{uuid4()}',{now_us()},NULL);"
            else:
                for previous, source in enumerate(scripts[:index], start=1):
                    digest = hashlib.sha256(source.encode()).hexdigest()
                    suffix += f"INSERT OR IGNORE INTO runtime_migration_checksums VALUES({previous},'{digest}');"
            try:
                self.conn.executescript(f"BEGIN EXCLUSIVE;\n{body}\n{suffix}\nPRAGMA user_version={index};\nCOMMIT;")
            except BaseException:
                self.conn.rollback()
                raise
        checks = dict(self.conn.execute("SELECT version,sha256 FROM runtime_migration_checksums"))
        for index, script in enumerate(scripts, 1):
            if checks.get(index) != hashlib.sha256(script.encode()).hexdigest():
                raise ValueError("Installed migration differs from application resources")

    def begin_run(self, settings, *, source, model_sha, model_manifest, start):
        site_id = stable_id("site:" + settings.site_name)
        camera_id = stable_id("camera:" + settings.camera_id)
        rule_json = json.dumps(asdict(settings.rules), sort_keys=True)
        rule_id = stable_id("rules:" + rule_json)
        model_id = stable_id("model:" + model_sha)
        run_id = str(uuid4())
        configs = {}
        with self.transaction() as conn:
            conn.execute("INSERT OR IGNORE INTO sites VALUES(?,?,?)", (site_id, settings.site_name, start))
            conn.execute("INSERT OR IGNORE INTO cameras VALUES(?,?,?,?,?,?,?,?,?)",
                         (camera_id, site_id, settings.camera_id, "configured-via-local-input", None, 1, 1, "{}", start))
            conn.execute("INSERT OR IGNORE INTO rule_sets VALUES(?,?,?)", (rule_id, rule_json, start))
            conn.execute("INSERT OR IGNORE INTO model_artifacts VALUES(?,?,?,?,?)",
                         (model_id, model_sha, "external-local-artifact", json.dumps(model_manifest), start))
            conn.execute("INSERT INTO engine_runs VALUES(?,?,?,?,?,?,?)",
                         (run_id, model_id, "0.2.0", json.dumps({"data_source": source, "identity_source": "anonymous",
                          "workspace_ids": [stable_id("workspace:" + settings.camera_id + ":" + z.id) for z in settings.zones],
                          'model_sha256': model_sha, 'calibration_revision': model_manifest.get('calibration_revision'),
                          'session_rules': asdict(settings.sessions),
                          'inference_runtime': {k: model_manifest[k] for k in ('provider','runtime_version','requested_device','execution_devices','device_name','precision','performance_hint','threads') if k in model_manifest}}), start, None, None))
            # A stopped/crashed run cannot carry occupied evidence into this run.
            old = conn.execute("SELECT id, start_utc_us,evidence_until_utc_us FROM zone_intervals WHERE end_utc_us IS NULL").fetchall()
            if any(start < row["evidence_until_utc_us"] for row in old):
                raise ValueError("Run would move the evidence clock backwards")
            for row in old:
                if row["evidence_until_utc_us"] == row["start_utc_us"]:
                    conn.execute("DELETE FROM zone_intervals WHERE id=?", (row["id"],))
                else:
                    conn.execute("UPDATE zone_intervals SET end_utc_us=evidence_until_utc_us WHERE id=?", (row["id"],))
            previous_runs = conn.execute("SELECT id FROM engine_runs WHERE ended_utc_us IS NULL AND id<>?", (run_id,)).fetchall()
            for previous in previous_runs:
                last = conn.execute("SELECT COALESCE(MAX(observed_utc_us),?) FROM event_log WHERE engine_run_id=?", (start,previous["id"])).fetchone()[0]
                conn.execute("UPDATE engine_runs SET ended_utc_us=?,termination_reason='INTERRUPTED' WHERE id=?", (last,previous["id"]))
                conn.execute("UPDATE camera_generations SET ended_utc_us=? WHERE engine_run_id=? AND ended_utc_us IS NULL", (last,previous["id"]))
                conn.execute("DELETE FROM track_visits WHERE generation_id IN (SELECT id FROM camera_generations WHERE engine_run_id=?) AND end_utc_us IS NULL AND start_utc_us=last_observed_utc_us", (previous["id"],))
                conn.execute("UPDATE track_visits SET end_utc_us=last_observed_utc_us WHERE generation_id IN (SELECT id FROM camera_generations WHERE engine_run_id=?) AND end_utc_us IS NULL", (previous["id"],))
                conn.execute("UPDATE person_sessions SET status='EXPIRED',track_id=NULL,track_lifecycle=NULL,reason='INTERRUPTED' WHERE engine_run_id=? AND status<>'EXPIRED'", (previous['id'],))
            desired = {stable_id('workspace:' + settings.camera_id + ':' + z.id) for z in settings.zones}
            for old_config in conn.execute("SELECT id,workspace_id FROM workspace_configurations WHERE camera_id=? AND effective_to_utc_us IS NULL", (camera_id,)).fetchall():
                if old_config['workspace_id'] not in desired:
                    conn.execute('UPDATE workspace_configurations SET effective_to_utc_us=? WHERE id=?', (start, old_config['id']))
                    conn.execute('UPDATE workspaces SET monitoring_to_utc_us=? WHERE id=?', (start, old_config['workspace_id']))
            for zone in settings.zones:
                workspace_id = stable_id("workspace:" + settings.camera_id + ":" + zone.id)
                conn.execute("INSERT OR IGNORE INTO workspaces VALUES(?,?,?,?,?,?,?,?)",
                             (workspace_id, site_id, zone.name, "desk", 1, zone.exclusive_group, start, None))
                conn.execute("UPDATE workspaces SET name=?,exclusive_group=?,monitoring_to_utc_us=NULL WHERE id=?", (zone.name, zone.exclusive_group, workspace_id))
                # Existing monitoring lifetime is immutable; changed geometry creates a revision.
                polygon = json.dumps(zone.polygon)
                active = conn.execute("SELECT * FROM workspace_configurations WHERE workspace_id=? AND effective_to_utc_us IS NULL", (workspace_id,)).fetchone()
                frame_width, frame_height = model_manifest.get('calibration_width', 1), model_manifest.get('calibration_height', 1)
                if active and (active["polygon_json"] != polygon or active["rule_set_id"] != rule_id or active['reference_width'] != frame_width or active['reference_height'] != frame_height):
                    if start <= active["effective_from_utc_us"]:
                        raise ValueError("Configuration must advance its effective timestamp")
                    conn.execute("UPDATE workspace_configurations SET effective_to_utc_us=? WHERE id=?", (start, active["id"]))
                    active = None
                if active:
                    config_id = active["id"]
                else:
                    revision = conn.execute("SELECT COALESCE(MAX(revision),0)+1 FROM workspace_configurations WHERE workspace_id=?", (workspace_id,)).fetchone()[0]
                    config_id = str(uuid4())
                    conn.execute("INSERT INTO workspace_configurations VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                                 (config_id, workspace_id, camera_id, rule_id, revision, polygon, frame_width, frame_height, "single-camera-calibrated" if frame_width > 1 else "single-camera-calibration-required", start, None))
                configs[zone.id] = (workspace_id, config_id)
        return RunWriter(self, run_id, camera_id, configs)

    def report(self, start, end, *, run_id=None):
        result = []
        allowed = None
        if run_id:
            manifest = self.conn.execute("SELECT runtime_manifest_json FROM engine_runs WHERE id=?", (run_id,)).fetchone()
            if manifest:
                allowed = json.loads(manifest[0]).get("workspace_ids")
        for workspace in self.conn.execute("SELECT * FROM workspaces ORDER BY name"):
            if allowed is not None and workspace["id"] not in allowed:
                continue
            left = max(start, workspace["monitoring_from_utc_us"])
            right = min(end, workspace["monitoring_to_utc_us"] or end)
            if right <= left:
                continue
            rows = self.conn.execute("SELECT * FROM zone_intervals WHERE workspace_id=? AND start_utc_us<? AND evidence_until_utc_us>? "
                                     + ("AND engine_run_id=? " if run_id else "") + "ORDER BY start_utc_us",
                                     (workspace["id"], right, left, *([run_id] if run_id else []))).fetchall()
            intervals = [Interval(State(r["state"]), r["start_utc_us"], r["evidence_until_utc_us"], r["observed_count"], r["reason"]) for r in rows]
            assignments = [dict(r) for r in self.conn.execute(
                "SELECT a.*,e.display_name FROM workstation_assignments a JOIN employees e ON e.id=a.employee_id "
                "WHERE a.workspace_id=? AND a.effective_from_utc_us<? AND COALESCE(a.effective_to_utc_us,9223372036854775807)>?",
                (workspace["id"], right, left))]
            result.append({"workspace_id": workspace["id"], "workspace": workspace["name"], **summarize(intervals, left, right),
                           "identity_source": "anonymous", "observed_employee_id": None,
                           "workstation_assignments": assignments, "assignment_is_observed_identity": False})
        sources = [r[0] for r in self.conn.execute("SELECT DISTINCT json_extract(runtime_manifest_json,'$.data_source') FROM engine_runs " + ("WHERE id=?" if run_id else ""), ([run_id] if run_id else []))]
        return {"basis": "monitoring_window", "schedule_applied": False, "data_sources": sources, "start_utc_us": start, "end_utc_us": end, "workstations": result}

    def add_employee(self, name):
        name = name.strip()
        if not 1 <= len(name) <= 120:
            raise ValueError("Employee name length must be 1 to 120")
        employee_id = str(uuid4())
        with self.transaction() as conn:
            conn.execute("INSERT INTO employees VALUES(?,?,1,?)", (employee_id, name, now_us()))
        return employee_id

    def assign(self, employee_id, workspace_id, start, end):
        with self.transaction() as conn:
            employee = conn.execute("SELECT active FROM employees WHERE id=?", (employee_id,)).fetchone()
            if not employee or not employee[0]:
                raise ValueError("Employee unavailable")
            conn.execute("INSERT INTO workstation_assignments VALUES(?,?,?,?,?,?)",
                         (str(uuid4()), workspace_id, employee_id, start, end, "manual_assignment"))


class RunWriter:
    def __init__(self, db, run_id, camera_id, configs):
        self.db, self.run_id, self.camera_id, self.configs = db, run_id, camera_id, configs
        self.seq = 0
        self.generation = None

    def commit(self, accumulators, observed_at, event_type="CHECKPOINT", *, generation, frame_seq, monotonic_ns, visits, transitions=(), sessions=(), session_events=(), mapping_version=0, emit_session_events=False):
        next_seq = self.seq + 1
        with self.db.transaction() as conn:
            event_seq = conn.execute("INSERT INTO event_log(event_id,engine_run_id,producer_seq,event_type,observed_utc_us,recorded_utc_us,payload_version,payload_json) VALUES(?,?,?,?,?,?,?,?)",
                                     (str(uuid4()), self.run_id, next_seq, event_type, observed_at, now_us(), 1,
                                      json.dumps({"identity_source": "anonymous", "generation_id": generation, "frame_seq": frame_seq, "monotonic_ns": str(monotonic_ns),
                                                  'mapping_version': mapping_version, 'sessions': sessions, 'session_events': session_events,
                                                  "zones": {k: [asdict(r) for r in v.snapshot()] for k, v in accumulators.items()}}))).lastrowid
            if generation != self.generation:
                conn.execute("UPDATE camera_generations SET ended_utc_us=? WHERE engine_run_id=? AND ended_utc_us IS NULL", (observed_at, self.run_id))
                conn.execute("INSERT INTO camera_generations VALUES(?,?,?,?,?,NULL)", (generation,self.run_id,self.camera_id,
                             conn.execute("SELECT COUNT(*)+1 FROM camera_generations WHERE engine_run_id=?", (self.run_id,)).fetchone()[0],observed_at))
            # Clear affected bindings first so a legitimate two-way tracker-ID
            # change cannot collide with another row halfway through the update.
            conn.executemany('UPDATE person_sessions SET track_id=NULL,track_lifecycle=NULL WHERE session_id=?',
                             [(s['session_id'],) for s in sessions])
            for session in sessions:
                values = (session['session_id'], self.run_id, self.camera_id, session['camera_id'], session['generation_id'],
                          session['first_seen_utc_us'], session['last_seen_utc_us'], session['accumulated_duration_us'],
                          session['status'], session['track_id'], session['track_lifecycle'], session['mapping_version'],
                          session['reason'], session['merged_into'], json.dumps(session['matching']),
                          json.dumps(session['zone_times']), event_seq)
                conn.execute('INSERT INTO person_sessions VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) '
                             'ON CONFLICT(session_id) DO UPDATE SET last_seen_utc_us=excluded.last_seen_utc_us,'
                             'accumulated_duration_us=excluded.accumulated_duration_us,status=excluded.status,'
                             'track_id=excluded.track_id,track_lifecycle=excluded.track_lifecycle,mapping_version=excluded.mapping_version,'
                             'reason=excluded.reason,merged_into=excluded.merged_into,matching_json=excluded.matching_json,'
                             'zone_times_json=excluded.zone_times_json,updated_event_seq=excluded.updated_event_seq', values)
            current_visits = {(track, self.configs[alias][0]) for track, alias in visits}
            active_visits = conn.execute("SELECT * FROM track_visits WHERE generation_id IN (SELECT id FROM camera_generations WHERE engine_run_id=?) AND end_utc_us IS NULL", (self.run_id,)).fetchall()
            for visit in active_visits:
                if (visit["track_id"],visit["workspace_id"]) not in current_visits or visit["generation_id"] != generation:
                    if visit["last_observed_utc_us"] == visit["start_utc_us"]:
                        conn.execute("DELETE FROM track_visits WHERE id=?", (visit["id"],))
                    else:
                        conn.execute("UPDATE track_visits SET end_utc_us=last_observed_utc_us WHERE id=?", (visit["id"],))
            for track, workspace in current_visits:
                existing = conn.execute("SELECT id FROM track_visits WHERE generation_id=? AND track_id=? AND workspace_id=? AND end_utc_us IS NULL", (generation,track,workspace)).fetchone()
                if existing:
                    conn.execute("UPDATE track_visits SET last_observed_utc_us=? WHERE id=?", (observed_at,existing["id"]))
                else:
                    conn.execute("INSERT INTO track_visits VALUES(?,?,?,?,?,?,?,?)", (str(uuid4()),generation,track,workspace,observed_at,None,observed_at,"anonymous"))
            for alias, accumulator in accumulators.items():
                workspace_id, config_id = self.configs[alias]
                conn.execute("DELETE FROM zone_intervals WHERE engine_run_id=? AND workspace_id=? AND start_utc_us=evidence_until_utc_us", (self.run_id, workspace_id))
                for row in accumulator.snapshot():
                    interval_id = stable_id(f"{self.run_id}:{workspace_id}:{row.start}")
                    if conn.execute("SELECT 1 FROM zone_intervals WHERE id=?", (interval_id,)).fetchone():
                        conn.execute("UPDATE zone_intervals SET state=?, observed_count=?,reason=?,end_utc_us=?,evidence_until_utc_us=?,updated_event_seq=? WHERE id=?",
                                     (row.state,row.count,row.reason,row.until if row.closed else None,row.until,event_seq,interval_id))
                    else:
                        conn.execute("INSERT INTO zone_intervals VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                                     (interval_id, workspace_id, config_id, self.run_id, row.state, row.count, row.reason, row.start,
                                      row.until if row.closed else None, row.until, event_seq, event_seq))
            # Zero-duration transient rows must not remain as open intervals.
            for workspace_id, _ in self.configs.values():
                active_start = next(a.current.start for alias, a in accumulators.items() if self.configs[alias][0] == workspace_id)
                conn.execute("DELETE FROM zone_intervals WHERE engine_run_id=? AND workspace_id=? AND start_utc_us= evidence_until_utc_us AND start_utc_us<>?", (self.run_id, workspace_id, active_start))
            for transition in (*transitions, *(session_events if emit_session_events else ())):
                next_seq += 1
                conn.execute("INSERT INTO event_log(event_id,engine_run_id,producer_seq,event_type,observed_utc_us,recorded_utc_us,payload_version,payload_json) VALUES(?,?,?,?,?,?,?,?)",
                    (str(uuid4()), self.run_id, next_seq, transition["type"], observed_at, now_us(), 1,
                     json.dumps({**transition, "generation_id": generation, "frame_seq": frame_seq, "identity_source": "anonymous"})))
        self.seq = next_seq
        self.generation = generation
        for accumulator in accumulators.values():
            accumulator.checkpoint()

    def finish(self, at, reason):
        with self.db.transaction() as conn:
            conn.execute("UPDATE person_sessions SET status='EXPIRED',track_id=NULL,track_lifecycle=NULL,reason=? WHERE engine_run_id=? AND status<>'EXPIRED'", (reason, self.run_id))
            conn.execute("UPDATE camera_generations SET ended_utc_us=? WHERE engine_run_id=? AND ended_utc_us IS NULL", (at,self.run_id))
            conn.execute("DELETE FROM track_visits WHERE generation_id IN (SELECT id FROM camera_generations WHERE engine_run_id=?) AND end_utc_us IS NULL AND start_utc_us=last_observed_utc_us", (self.run_id,))
            conn.execute("UPDATE track_visits SET end_utc_us=last_observed_utc_us WHERE generation_id IN (SELECT id FROM camera_generations WHERE engine_run_id=?) AND end_utc_us IS NULL", (self.run_id,))
            conn.execute("DELETE FROM zone_intervals WHERE engine_run_id=? AND end_utc_us IS NULL AND start_utc_us=evidence_until_utc_us", (self.run_id,))
            conn.execute("UPDATE zone_intervals SET end_utc_us=evidence_until_utc_us WHERE engine_run_id=? AND end_utc_us IS NULL", (self.run_id,))
            conn.execute("UPDATE engine_runs SET ended_utc_us=?,termination_reason=? WHERE id=?", (at, reason, self.run_id))
