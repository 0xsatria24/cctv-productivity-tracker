from dataclasses import dataclass
from collections import deque
from pathlib import Path
import hashlib
import json
import logging

from .domain.occupancy import Observation, State, ZoneAccumulator
from .vision import Detection, Tracker, associate
from .lease import EngineLease
from .persistence import stable_id
from .sessions import SessionManager


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
        self.sessions = SessionManager(settings)
        self.last_monotonic_ns = None
        self.last_generation = None
        self.clock_anchor = None
        self.latest = None
        self.retired_generations = deque(maxlen=16)

    def feed(self, detections, utc_us, monotonic_ns, seq, generation, unavailable=None, *, mapping_version=None):
        # Reject before ANY tracker/session/zone mutation. A result from a retired
        # frame cannot rebind a session or advance the durable checkpoint.
        if (generation in self.retired_generations or
                (mapping_version is not None and mapping_version != self.sessions.mapping_version) or
                (self.last_monotonic_ns is not None and (monotonic_ns <= self.last_monotonic_ns
                or (generation == self.last_generation and seq <= self.last_sequence)))):
            self.sessions._diagnose('stale_result')
            return {**(self.latest or {}), 'ignored': True, 'ignore_reason': 'STALE_FRAME', 'detections': []}
        if seq < 1 or monotonic_ns < 0 or utc_us < 0 or not generation or (self.clock_anchor is None and utc_us < self.start):
            raise ValueError('Invalid pipeline observation envelope')
        captured_utc_us = utc_us
        if self.clock_anchor is None:
            self.clock_anchor = (utc_us, monotonic_ns)
        # UTC is a calendar anchor; elapsed time follows monotonic/media time.
        utc_us = self.clock_anchor[0] + (monotonic_ns - self.clock_anchor[1]) // 1000
        scoped_generation = stable_id(self.writer.run_id + ":" + generation)
        visits = []
        tracked = []
        if unavailable:
            mapped = {z.id: (State.UNKNOWN, None, unavailable) for z in self.settings.zones}
        else:
            tracked = self.tracker.update(detections, monotonic_ns / 1e9, scoped_generation)
            mapped = associate(tracked, self.settings.zones, self.settings.rules)
        bindings = self.sessions.update(tracked, utc_us, monotonic_ns, scoped_generation, unavailable)
        for detection, session in bindings:
            if session is not None:
                visits.extend((session.track_lifecycle, alias) for alias, zone in session.zones.items() if zone.observed_inside)
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
        session_rows = self.sessions.rows()
        session_snapshots = {row['session_id']: row for row in session_rows}
        try:
            self.writer.commit(self.accumulators, utc_us, generation=scoped_generation, frame_seq=seq, monotonic_ns=monotonic_ns,
                               visits=visits, transitions=transitions, sessions=session_rows,
                               session_events=self.sessions.events, mapping_version=self.sessions.mapping_version,
                               emit_session_events=self.live_events)
        except Exception:
            # The owning command aborts; uncommitted memory is never retried as evidence.
            logging.getLogger("cctv_tracker").error("PERSISTENCE_GAP: accounting stopped")
            raise
        self.last_utc = utc_us
        if self.last_generation is not None and self.last_generation != generation:
            self.retired_generations.append(self.last_generation)
        self.last_monotonic_ns, self.last_sequence, self.last_generation = monotonic_ns, seq, generation
        # These exact session snapshots have committed in the same transaction.
        # Each overlay pairs a CURRENT measured box with that binding's timer.
        rows = []
        for detection, session in bindings:
            snapshot = session_snapshots[session.session_id] if session else None
            rows.append({**dataclass_detection(detection), 'track_id': session.track_id if session else None,
                         'session_id': session.session_id if session else None,
                         'track_lifecycle': session.track_lifecycle if session else None,
                         'mapping_version': self.sessions.mapping_version,
                         'first_seen_utc_us': session.first_seen if session else None,
                         'last_seen_utc_us': session.last_seen if session else None,
                         'accumulated_duration_us': session.accumulated_ns // 1000 if session else 0,
                         'session_status': session.status if session else 'UNASSIGNED',
                         'workstation_times': [{'zone_id': alias, 'name': next(z.name for z in self.settings.zones if z.id == alias),
                                                'presence_us': zone['presence_us']}
                                               for alias, zone in (snapshot['zone_times'].items() if snapshot else ()) if zone['inside']]})
        self.latest = {"run_id": self.writer.run_id, "committed_sequence": self.writer.seq,
                'frame_seq': seq, 'generation_id': scoped_generation, 'mapping_version': self.sessions.mapping_version,
                'frame_monotonic_ns': str(monotonic_ns), 'captured_utc_us': captured_utc_us,
                'sessions': [session_snapshots.get(s.session_id) or self.sessions.snapshot(s) for s in self.sessions.sessions.values()],
                'session_metrics': dict(self.sessions.metrics),
                "detections": rows,
                "zones": [{"id": alias, "name": next(z.name for z in self.settings.zones if z.id == alias),
                           "state": a.current.state, "count": a.current.count, "reason": a.current.reason,
                           "state_since_utc_us": a.current.start, "evidence_until_utc_us": a.current.until}
                          for alias, a in self.accumulators.items()]}
        self.sessions.checkpoint()
        return self.latest

    def finish(self, reason="COMPLETED"):
        try:
            self.writer.finish(self.last_utc, reason)
            return self.database.report(self.start, max(self.last_utc, self.start + 1), run_id=self.writer.run_id)
        finally:
            self.sessions.finish()
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
