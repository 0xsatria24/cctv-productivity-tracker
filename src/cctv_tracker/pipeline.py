from dataclasses import dataclass
from pathlib import Path
import hashlib
import json
import logging

from .domain.occupancy import Observation, State, ZoneAccumulator
from .vision import Detection, Tracker, associate
from .lease import EngineLease
from .persistence import stable_id


class Pipeline:
    def __init__(self, settings, database, start, source, model_sha, model_manifest, *, live_events=False):
        if not settings.zones:
            raise ValueError("At least one calibrated zone is required")
        self.settings, self.database, self.start, self.last_utc = settings, database, start, start
        self.tracker = Tracker(settings.inference_fps, settings.rules.max_evidence_gap_seconds)
        self.accumulators = {z.id: ZoneAccumulator(start, settings.rules) for z in settings.zones}
        self.lease = EngineLease(database.path)
        try:
            self.writer = database.begin_run(settings, source=source, model_sha=model_sha, model_manifest=model_manifest, start=start)
        except BaseException:
            self.lease.close()
            raise
        self.last_sequence = None
        self.live_events = live_events
        self.confirmed = {}

    def feed(self, detections, utc_us, monotonic_ns, seq, generation, unavailable=None):
        scoped_generation = stable_id(self.writer.run_id + ":" + generation)
        visits = []
        tracked = []
        if unavailable:
            mapped = {z.id: (State.UNKNOWN, None, unavailable) for z in self.settings.zones}
        else:
            tracked = self.tracker.update(detections, monotonic_ns / 1e9, scoped_generation)
            mapped = associate(tracked, self.settings.zones, self.settings.rules)
            for detection in tracked:
                if detection.track_id is None:
                    continue
                targets = associate([detection], self.settings.zones, self.settings.rules)
                visits.extend((detection.track_id, alias) for alias, row in targets.items() if row[0] == State.OCCUPIED)
        previous_states = {alias: a.current.state for alias, a in self.accumulators.items()}
        previous_candidates = {alias: a.candidate for alias, a in self.accumulators.items()}
        for alias, accumulator in self.accumulators.items():
            state, count, reason = mapped[alias]
            accumulator.feed(Observation(utc_us, monotonic_ns, seq, generation, state, count, reason))
        transitions = []
        if self.live_events:
            for alias, accumulator in self.accumulators.items():
                current = accumulator.current
                if current.state != State.UNKNOWN and previous_states[alias] != current.state:
                    candidate = previous_candidates[alias]
                    transitions.append({"type": "ENTER" if current.state == State.OCCUPIED else "EXIT" if self.confirmed.get(alias) == State.OCCUPIED else "EMPTY_CONFIRMED",
                                        "zone_id": alias, "state": current.state, "count": current.count,
                                        "evidence_first_utc_us": utc_us - (monotonic_ns - candidate[1]) // 1000 if candidate else utc_us,
                                        "confirmation_utc_us": utc_us})
                    self.confirmed[alias] = current.state
        try:
            self.writer.commit(self.accumulators, utc_us, generation=scoped_generation, frame_seq=seq, monotonic_ns=monotonic_ns, visits=visits, transitions=transitions)
        except Exception:
            # The owning command aborts; uncommitted memory is never retried as evidence.
            logging.getLogger("cctv_tracker").error("PERSISTENCE_GAP: accounting stopped")
            raise
        self.last_utc = utc_us
        # Use the committed visit timestamps for each person's current workstation
        # timer. A new track/visit gets its own clock, never another occupant's time.
        active_visits = self.database.conn.execute(
            'SELECT track_id, workspace_id, start_utc_us, last_observed_utc_us FROM track_visits '
            'WHERE generation_id=? AND end_utc_us IS NULL', (scoped_generation,)).fetchall()
        workstation_times = {}
        for visit in active_visits:
            alias = next(alias for alias, config in self.writer.configs.items() if config[0] == visit['workspace_id'])
            workstation_times.setdefault(visit['track_id'], []).append({
                'zone_id': alias, 'name': next(z.name for z in self.settings.zones if z.id == alias),
                'presence_us': max(0, visit['last_observed_utc_us'] - visit['start_utc_us']),
            })
        return {"run_id": self.writer.run_id, "committed_sequence": self.writer.seq,
                "detections": [{**dataclass_detection(d), 'workstation_times': workstation_times.get(d.track_id, [])} for d in tracked],
                "zones": [{"id": alias, "name": next(z.name for z in self.settings.zones if z.id == alias),
                           "state": a.current.state, "count": a.current.count, "reason": a.current.reason,
                           "state_since_utc_us": a.current.start, "evidence_until_utc_us": a.current.until}
                          for alias, a in self.accumulators.items()]}

    def finish(self, reason="COMPLETED"):
        try:
            self.writer.finish(self.last_utc, reason)
            return self.database.report(self.start, max(self.last_utc, self.start + 1), run_id=self.writer.run_id)
        finally:
            self.lease.close()


def dataclass_detection(d):
    return {"box": d.box, "confidence": d.confidence, "track_id": d.track_id}


def replay(path: Path, settings, database):
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("data_source") != "SYNTHETIC_REPLAY" or not payload.get("frames"):
        raise ValueError("Replay must explicitly declare SYNTHETIC_REPLAY and contain frames")
    from .config import timestamp
    start = timestamp(payload["start"])
    pipeline = Pipeline(settings, database, start, "SYNTHETIC_REPLAY", hashlib.sha256(path.read_bytes()).hexdigest(),
                        {"license": "local synthetic test fixture", "source": "replay detections, not model inference"})
    try:
        for frame in payload["frames"]:
            elapsed = frame["elapsed_seconds"]
            detections = [Detection(tuple(d["box"]), d["confidence"]) for d in frame.get("detections", [])]
            pipeline.feed(detections, start + round(elapsed * 1_000_000), round(elapsed * 1e9), frame["seq"], frame.get("generation", "replay-1"), frame.get("unavailable"))
    except BaseException:
        pipeline.finish("INTERRUPTED")
        raise
    result = pipeline.finish()
    return {"run_id": pipeline.writer.run_id, **result}
