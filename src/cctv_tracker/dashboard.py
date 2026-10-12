"""Durable dashboard queries and a cancellable synthetic replay worker."""
from contextlib import closing
from importlib.resources import files
from threading import Event, Lock, Thread
import hashlib
import json
import logging

from .config import timestamp
from .persistence import Database
from .pipeline import Pipeline
from .vision import Detection


class ReplayController:
    def __init__(self, settings, *, delay=0.10):
        self.settings, self.delay = settings, delay
        self.lock, self.stop_event = Lock(), Event()
        self.thread = None
        self.state = {"status": "IDLE", "processed": 0, "total": 0, "run_id": None, "error": None}

    def snapshot(self):
        with self.lock:
            return dict(self.state)

    def start(self):
        with self.lock:
            if self.thread and self.thread.is_alive():
                raise ValueError("Replay masih berjalan")
            with closing(Database(self.settings.database, migrate=False)) as db:
                other_source = db.conn.execute("SELECT 1 FROM engine_runs WHERE COALESCE(json_extract(runtime_manifest_json,'$.data_source'),'UNKNOWN')<>'SYNTHETIC_REPLAY' LIMIT 1").fetchone()
            if other_source:
                raise ValueError("Replay sintetis memerlukan database pilot terpisah; database ini memiliki sumber lain")
            self.stop_event.clear()
            self.state = {"status": "QUEUED", "processed": 0, "total": 0, "run_id": None, "error": None}
            self.thread = Thread(target=self._run, name="occupancy-replay", daemon=False)
            self.thread.start()
            return dict(self.state)

    def stop(self):
        self.stop_event.set()
        return self.snapshot()

    def shutdown(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=15)

    def _update(self, **values):
        with self.lock:
            self.state.update(values)

    def _run(self):
        pipeline = None
        try:
            resource = files("cctv_tracker").joinpath("resources", "occupancy-replay.json")
            payload = json.loads(resource.read_text(encoding="utf-8"))
            frames = payload["frames"]
            with closing(Database(self.settings.database)) as db:
                watermark = db.conn.execute("SELECT MAX(evidence_until_utc_us) FROM zone_intervals").fetchone()[0]
                start = max(timestamp(payload["start"]), (watermark + 1_000_000) if watermark is not None else 0)
                pipeline = Pipeline(self.settings, db, start, "SYNTHETIC_REPLAY", hashlib.sha256(resource.read_bytes()).hexdigest(),
                                    {"license": "local synthetic test fixture", "source": "dashboard replay detections"})
                self._update(status="RUNNING", total=len(frames), run_id=pipeline.writer.run_id)
                for i, frame in enumerate(frames):
                    if self.stop_event.is_set():
                        break
                    elapsed = frame["elapsed_seconds"]
                    detections = [Detection(tuple(d["box"]), d["confidence"]) for d in frame.get("detections", [])]
                    pipeline.feed(detections, start + round(elapsed * 1e6), round(elapsed * 1e9), frame["seq"], frame.get("generation", "replay-1"), frame.get("unavailable"))
                    self._update(processed=i + 1)
                    if self.delay and self.stop_event.wait(self.delay):
                        break
                pipeline.finish("CANCELLED" if self.stop_event.is_set() else "COMPLETED")
                pipeline = None
                self._update(status="CANCELLED" if self.stop_event.is_set() else "COMPLETED")
        except Exception as error:
            if pipeline:
                try:
                    pipeline.finish("INTERRUPTED")
                except Exception:
                    pipeline.lease.close()
            logging.getLogger("cctv_tracker").error("Dashboard replay failed: %s", type(error).__name__)
            self._update(status="FAILED", error="Replay gagal. Periksa log engine; data committed tetap tersedia.")


def snapshot(db, controller=None, timezone="Asia/Jakarta"):
    conn = db.conn
    runs = [dict(row) for row in conn.execute(
        "SELECT r.id,r.started_utc_us,r.ended_utc_us,r.termination_reason,"
        "json_extract(r.runtime_manifest_json,'$.data_source') AS data_source,"
        "(SELECT MAX(observed_utc_us) FROM event_log e WHERE e.engine_run_id=r.id) AS durable_until_utc_us "
        "FROM engine_runs r ORDER BY r.started_utc_us DESC LIMIT 100")]
    workspaces = []
    for row in conn.execute("SELECT w.id,w.name,w.kind,w.capacity,w.exclusive_group,c.id AS configuration_id,c.revision,c.camera_id,c.polygon_json "
                            "FROM workspaces w JOIN workspace_configurations c ON c.workspace_id=w.id WHERE c.effective_to_utc_us IS NULL ORDER BY w.name"):
        item = dict(row)
        item["polygon"] = json.loads(item.pop("polygon_json"))
        last = conn.execute("SELECT state,observed_count,reason,evidence_until_utc_us FROM zone_intervals WHERE workspace_id=? ORDER BY start_utc_us DESC LIMIT 1", (item["id"],)).fetchone()
        item["last_observation"] = dict(last) if last else None
        workspaces.append(item)
    events = []
    for row in conn.execute("SELECT seq,event_id,event_type,engine_run_id,observed_utc_us,payload_json FROM event_log ORDER BY seq DESC LIMIT 100"):
        item = dict(row)
        payload = json.loads(item.pop("payload_json"))
        item["frame_seq"] = payload.get("frame_seq")
        item["generation_id"] = payload.get("generation_id")
        item["zone_states"] = {alias: values[-1]["state"] for alias, values in payload.get("zones", {}).items() if values}
        events.append(item)
    return {"mode": "integrated_replay_pilot" if controller else "read_only_pilot", "schema_version": conn.execute("PRAGMA user_version").fetchone()[0],
            "identity_source": "anonymous", "face_recognition_enabled": False, "live_capture_available": False, "timezone": timezone,
            "committed_event_seq": conn.execute("SELECT COALESCE(MAX(seq),0) FROM event_log").fetchone()[0],
            "controller": controller.snapshot() if controller else None, "runs": runs, "workspaces": workspaces, "events": events,
            "cameras": [dict(r) for r in conn.execute("SELECT id,name,enabled,revision FROM cameras ORDER BY name")],
            "employees": [dict(r) for r in conn.execute("SELECT id,display_name,active FROM employees ORDER BY display_name")],
            "assignments": [dict(r) for r in conn.execute("SELECT a.*,e.display_name,w.name AS workspace_name FROM workstation_assignments a JOIN employees e ON e.id=a.employee_id JOIN workspaces w ON w.id=a.workspace_id ORDER BY a.effective_from_utc_us DESC LIMIT 100")]}


def report(db, start=None, end=None, run_id=None, workspace_id=None):
    params = () if not run_id else (run_id,)
    where = "" if not run_id else "WHERE id=?"
    bounds = db.conn.execute(f"SELECT MIN(started_utc_us),MAX(COALESCE(ended_utc_us,(SELECT MAX(observed_utc_us) FROM event_log e WHERE e.engine_run_id=engine_runs.id))) FROM engine_runs {where}", params).fetchone()
    if run_id and bounds[0] is None:
        raise LookupError("Run tidak ditemukan")
    explicit_range = start is not None or end is not None
    start = start if start is not None else bounds[0]
    end = end if end is not None else bounds[1]
    if start is not None and end is not None and end <= start:
        if not explicit_range and bounds[0] == bounds[1]:
            end = None
        else:
            raise ValueError("Invalid report range")
    if start is None or end is None:
        return {"basis": "monitoring_window", "schedule_applied": False, "start_utc_us": start, "end_utc_us": end,
                "workstations": [], "intervals": [], "data_sources": [], "committed_event_seq": 0}
    if start < 0:
        raise ValueError("Invalid report range")
    result = db.report(start, end, run_id=run_id)
    if workspace_id:
        result["workstations"] = [r for r in result["workstations"] if r["workspace_id"] == workspace_id]
    intervals = []
    for workspace in result["workstations"]:
        cursor = max(start, db.conn.execute("SELECT monitoring_from_utc_us FROM workspaces WHERE id=?", (workspace["workspace_id"],)).fetchone()[0])
        raw = db.conn.execute("SELECT z.*,c.revision FROM zone_intervals z JOIN workspace_configurations c ON c.id=z.configuration_id WHERE z.workspace_id=? AND z.start_utc_us<? AND z.evidence_until_utc_us>? "
                              + ("AND z.engine_run_id=? " if run_id else "") + "ORDER BY z.start_utc_us", (workspace["workspace_id"], end, start, *([run_id] if run_id else [])))
        for row in raw:
            left, right = max(cursor, row["start_utc_us"]), min(end, row["evidence_until_utc_us"])
            if right <= left:
                continue
            if left > cursor:
                intervals.append({"id": f"gap:{workspace['workspace_id']}:{cursor}", "workspaceId": workspace["workspace_id"], "start": cursor / 1000, "end": left / 1000, "state": "UNKNOWN", "count": None, "reason": "ENGINE_INTERRUPTED", "revision": None})
            intervals.append({"id": row["id"], "workspaceId": workspace["workspace_id"], "start": left / 1000, "end": right / 1000, "state": row["state"], "count": row["observed_count"], "reason": row["reason"], "revision": row["revision"]})
            cursor = right
        if cursor < end:
            intervals.append({"id": f"tail:{workspace['workspace_id']}:{cursor}", "workspaceId": workspace["workspace_id"], "start": cursor / 1000, "end": end / 1000, "state": "UNKNOWN", "count": None, "reason": "FRAME_STALE", "revision": None})
    result["intervals"] = intervals
    result["committed_event_seq"] = db.conn.execute("SELECT COALESCE(MAX(seq),0) FROM event_log").fetchone()[0]
    return result
