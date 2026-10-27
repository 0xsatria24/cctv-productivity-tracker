from dataclasses import dataclass, replace
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
from .positioning import measured_position
from .reid.runtime import ReIdRuntime
from .reid.types import FrameToken
from .workstation_engine import workstation_observations, workstation_markers, workstation_checkins


class Pipeline:
    def __init__(self, settings, database, start, source, model_sha, model_manifest, *, live_events=False, reid_extractor=None, area_mode=False, markers=()):
        if not area_mode and settings.reid.mode == 'active' and settings.sessions.count_lost_gap:
            raise ValueError('Accounting ReID requires count_lost_gap=false')
        if not settings.zones:
            raise ValueError("At least one calibrated zone is required")
        self.settings, self.database, self.start, self.last_utc = settings, database, start, start
        self.area_mode = area_mode
        self.tracker = None if area_mode else Tracker(settings.inference_fps, settings.rules.max_evidence_gap_seconds, rules=settings.tracking)
        self.accumulators = {z.id: ZoneAccumulator(start, settings.rules) for z in settings.zones}
        self.lease = EngineLease(database.path)
        try:
            self.writer = database.begin_run(settings, source=source, model_sha=model_sha,
                                            model_manifest={**model_manifest,'analysis_mode':'workstation' if area_mode else 'person'}, start=start)
        except BaseException:
            self.lease.close()
            raise
        self.last_sequence = None
        self.live_events = live_events
        self.confirmed = {}
        self.sessions = None if area_mode else SessionManager(settings, continuation_confidence=min(
            settings.detection.tracking_confidence, settings.rules.strong_confidence))
        self.last_monotonic_ns = None
        self.last_generation = None
        self.clock_anchor = None
        self.latest = None
        self.retired_generations = deque(maxlen=16)
        self.reid = None if area_mode else ReIdRuntime(replace(settings.reid, recovery_policy='motion'), reid_extractor)
        self.area_totals = {z.id: {state: 0 for state in State} for z in settings.zones}
        from .aruco import ArucoReader, MarkerCheckIns
        self.marker_reader = ArucoReader() if area_mode and markers else None
        self.checkins = MarkerCheckIns(list(markers)) if area_mode else None

    def feed(self, detections, utc_us, monotonic_ns, seq, generation, unavailable=None, *, mapping_version=None, frame_jpeg=None):
        # Reject before ANY tracker/session/zone mutation. A result from a retired
        # frame cannot rebind a session or advance the durable checkpoint.
        if (generation in self.retired_generations or
                (mapping_version is not None and mapping_version != (self.sessions.mapping_version if self.sessions else 0)) or
                (self.last_monotonic_ns is not None and (monotonic_ns <= self.last_monotonic_ns
                or (generation == self.last_generation and seq <= self.last_sequence)))):
            if self.sessions:
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
            mapped = workstation_observations([], self.settings, unavailable)
        else:
            tracked = [d for d in detections if not d.tracking_only] if self.area_mode else self.tracker.update(detections, monotonic_ns / 1e9, scoped_generation)
            mapped = workstation_observations(tracked, self.settings) if self.area_mode else associate(
                [d for d in tracked if not d.tracking_only], self.settings.zones, self.settings.rules, self.settings.position)
        if self.area_mode:
            bindings = [(d, None) for d in tracked]
            mapping = 0
            reid_stage = {'report': {'mode': 'off', 'status': 'OFF', 'decisions': []}}
        else:
            bindings = self.sessions.update(tracked, utc_us, monotonic_ns, scoped_generation, unavailable,
                                            recover=self.settings.reid.mode != 'active')
            mapping = self.sessions.mapping_version
            token = FrameToken(self.settings.camera_id, self.writer.run_id, scoped_generation, seq, monotonic_ns, mapping)
            reid_stage = self.reid.prepare(frame_jpeg, tracked, token, self.sessions, bindings, unavailable)
            bindings = self.reid.apply(reid_stage, self.sessions, bindings)
            mapping = self.sessions.mapping_version
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
        session_rows = self.sessions.rows() if self.sessions else []
        session_snapshots = {row['session_id']: row for row in session_rows}
        area_deltas = {alias: {state: sum(max(0, min(utc_us, row.until)-max(self.last_utc, row.start))
                                        for row in a.snapshot() if row.state == state) for state in State}
                       for alias, a in self.accumulators.items()}
        try:
            self.writer.commit(self.accumulators, utc_us, generation=scoped_generation, frame_seq=seq, monotonic_ns=monotonic_ns,
                               visits=visits, transitions=transitions, sessions=session_rows,
                               session_events=self.sessions.events if self.sessions else (), mapping_version=mapping,
                               emit_session_events=self.live_events,
                               reid_decisions=[d for d in reid_stage['report']['decisions'] if d['reason'] != 'NO_ELIGIBLE_GALLERY']
                                              if self.reid and self.settings.reid.mode == 'active' else (),
                               reid_model=reid_stage['report'].get('model'))
        except Exception:
            # The owning command aborts; uncommitted memory is never retried as evidence.
            logging.getLogger("cctv_tracker").error("PERSISTENCE_GAP: accounting stopped")
            raise
        self.last_utc = utc_us
        for alias, values in area_deltas.items():
            for state, duration in values.items():
                self.area_totals[alias][state] += duration
        reid_report = self.reid.commit(reid_stage, set(self.sessions.sessions)) if self.reid else reid_stage['report']
        if self.checkins and self.last_generation != generation:
            self.checkins = type(self.checkins)([{'marker_id': mid, 'label': label} for mid, label in self.checkins.registry.items()])
        if self.last_generation is not None and self.last_generation != generation:
            self.retired_generations.append(self.last_generation)
        self.last_monotonic_ns, self.last_sequence, self.last_generation = monotonic_ns, seq, generation
        # These exact session snapshots have committed in the same transaction.
        # Each overlay pairs a CURRENT measured box with that binding's timer.
        rows = []
        for detection, session in bindings:
            if detection.tracking_only:
                continue
            snapshot = session_snapshots[session.session_id] if session else None
            rows.append({**dataclass_detection(detection),
                         'position': measured_position(detection, self.settings.position) if self.settings.position.mode != 'bbox_overlap' else None,
                         'track_id': session.track_id if session else None,
                         'session_id': session.session_id if session else None,
                         'track_lifecycle': session.track_lifecycle if session else None,
                         'mapping_version': mapping,
                         'first_seen_utc_us': session.first_seen if session else None,
                         'last_seen_utc_us': session.last_seen if session else None,
                         'accumulated_duration_us': session.accumulated_ns // 1000 if session else 0,
                         'observed_duration_us': snapshot['observed_duration_us'] if snapshot else 0,
                         'total_elapsed_us': snapshot['total_elapsed_us'] if snapshot else 0,
                         'absence_duration_us': snapshot['absence_duration_us'] if snapshot else 0,
                         'evidence_state': 'MEASURED' if detection.confidence >= self.settings.rules.strong_confidence else 'WEAK',
                         'session_status': session.status if session else 'UNASSIGNED',
                         'workstation_times': [{'zone_id': alias, 'name': next(z.name for z in self.settings.zones if z.id == alias),
                                                'presence_us': zone['presence_us']}
                                               for alias, zone in (snapshot['zone_times'].items() if snapshot else ()) if zone['inside'] and session.last_observation_strong]})
        self.latest = {"run_id": self.writer.run_id, "committed_sequence": self.writer.seq,
                'frame_seq': seq, 'generation_id': scoped_generation, 'mapping_version': mapping,
                'frame_monotonic_ns': str(monotonic_ns), 'captured_utc_us': captured_utc_us,
                'sessions': [session_snapshots.get(s.session_id) or self.sessions.snapshot(s) for s in self.sessions.sessions.values()] if self.sessions else [],
                'session_metrics': dict(self.sessions.metrics) if self.sessions else {},
                'reid': reid_report,
                'tracking': {'algorithm': None, 'available': False, 'reason': 'WORKSTATION_MODE'} if self.area_mode else {'algorithm': 'ByteTrack', 'available': False, 'reason': unavailable}
                            if unavailable else dict(getattr(self.tracker, 'metrics', {})),
                "detections": rows,
                "zones": [{"id": alias, "name": next(z.name for z in self.settings.zones if z.id == alias),
                           "state": a.current.state, "count": a.current.count, "reason": a.current.reason,
                           "state_since_utc_us": a.current.start, "evidence_until_utc_us": a.current.until}
                          for alias, a in self.accumulators.items()]}
        stations = [{'zone_id': z.id, 'name': z.name, 'state': self.accumulators[z.id].current.state,
                     'count': self.accumulators[z.id].current.count, 'reason': self.accumulators[z.id].current.reason,
                     'occupied_us': self.area_totals[z.id][State.OCCUPIED], 'empty_us': self.area_totals[z.id][State.EMPTY],
                     'unknown_us': self.area_totals[z.id][State.UNKNOWN], 'observed_us': sum(self.area_totals[z.id].values())}
                    for z in self.settings.zones]
        if self.checkins:
            markers = workstation_markers(self.marker_reader, frame_jpeg, bool(self.checkins.registry), unavailable)
            stations = workstation_checkins(self.checkins, markers, stations, tracked, self.settings, (utc_us-self.start)/1e6)
            self.latest['aruco'] = markers
        self.latest.update(workstations=stations, analysis_mode='workstation' if self.area_mode else 'person')
        if self.sessions:
            self.sessions.checkpoint()
        return self.latest

    def finish(self, reason="COMPLETED"):
        try:
            self.writer.finish(self.last_utc, reason)
            return self.database.report(self.start, max(self.last_utc, self.start + 1), run_id=self.writer.run_id)
        finally:
            if self.sessions:
                self.sessions.finish()
                self.reid.clear()
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
