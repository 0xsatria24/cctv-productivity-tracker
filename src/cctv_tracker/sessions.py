"""Bounded anonymous sessions. Tracker IDs are hints, never identity evidence.

Motion-only recovery deliberately refuses stationary replacements, exits and
ambiguous crossings. It cannot recognize a person returning from off camera.
All time arithmetic uses the supplied monotonic/media timeline in nanoseconds.
"""
from collections import Counter, deque
from dataclasses import dataclass, field
import logging
import math
from uuid import uuid4

from .domain.occupancy import State
from .vision import associate

NS = 1_000_000_000


def center(box):
    return ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)


@dataclass
class ZoneTime:
    first_seen: int
    last_seen: int
    duration_ns: int = 0
    inside: bool = True
    observed_inside: bool = True
    outside_count: int = 0


@dataclass
class PersonSession:
    session_id: str
    camera_id: str
    generation: str
    first_seen: int
    last_seen: int
    first_ns: int
    last_ns: int
    box: tuple
    history: deque
    origin_box: tuple | None = None
    accumulated_ns: int = 0
    status: str = 'ACTIVE'
    track_id: str | None = None
    track_lifecycle: str | None = None
    zones: dict = field(default_factory=dict)
    recoverable: bool = True
    candidate_id: str | None = None
    candidate_votes: int = 0
    candidate_since_ns: int = 0
    reason: str | None = None
    merged_into: str | None = None
    last_observation_strong: bool = True
    last_strong_ns: int | None = None
    observed_ns: int = 0


class SessionManager:
    def __init__(self, settings, *, continuation_confidence=None):
        self.settings, self.rules = settings, settings.sessions
        self.sessions = {}
        self.dirty = {}
        self.events = []
        self.mapping_version = 0
        self.generation = None
        self.now_ns = None
        self.metrics = Counter()
        self._velocity_cache = {}
        self.continuation_confidence = continuation_confidence
        if continuation_confidence is not None and not 0 < continuation_confidence <= settings.rules.strong_confidence:
            raise ValueError('Continuation confidence must not exceed strong evidence threshold')

    def _diagnose(self, action, **values):
        self.metrics[action] += 1
        if self.rules.diagnostics:
            logging.getLogger('cctv_tracker.sessions').info('%s %s', action, values)

    def _event(self, action, session, **values):
        self.dirty[session.session_id] = session
        self.events.append({'type': 'SESSION_' + action, 'session_id': session.session_id,
                            'camera_id': session.camera_id, 'status': session.status,
                            'track_id': session.track_id, 'track_lifecycle': session.track_lifecycle,
                            'mapping_version': self.mapping_version, **values})
        self._diagnose(action.lower(), session_id=session.session_id, **values)

    def _bind(self, session, detection, generation):
        # A new lifecycle is allocated after every loss, even if raw ID is reused.
        if session.track_lifecycle is None or session.track_id != detection.track_id:
            self.mapping_version += 1
            session.track_lifecycle = f'{generation}:session-track:{self.mapping_version}'
            session.track_id = detection.track_id
            self._event('MAPPING', session)

    def _lose(self, session, reason, *, block=False):
        if block:
            session.recoverable = False
        if session.status == 'ACTIVE':
            session.status = 'LOST'
            session.track_id = session.track_lifecycle = None
            session.reason = reason
            session.candidate_id, session.candidate_votes = None, 0
            self.mapping_version += 1
            self._event('LOST', session, reason=reason)
        self.dirty[session.session_id] = session

    def _expire(self, session, reason):
        session.status, session.reason = 'EXPIRED', reason
        session.track_id = session.track_lifecycle = None
        self.mapping_version += 1
        self._event('EXPIRED', session, reason=reason)
        self.sessions.pop(session.session_id, None)

    def _velocity(self, session):
        key = (session.session_id, session.last_ns, len(session.history))
        if key not in self._velocity_cache:
            self._velocity_cache[key] = self._estimate_velocity(session)
        return self._velocity_cache[key]

    def _estimate_velocity(self, session):
        history = session.history
        if len(history) < 3:
            return None
        elapsed = (history[-1][0] - history[0][0]) / NS
        if elapsed < self.rules.recovery_confirm_seconds:
            return None
        first, last = center(history[0][1]), center(history[-1][1])
        velocity = ((last[0] - first[0]) / elapsed, (last[1] - first[1]) / elapsed)
        speed = math.hypot(*velocity)
        if speed < self.rules.minimum_motion_speed or speed > 1:
            return None
        # Require coherent motion throughout the bounded history, not two endpoints.
        for (ta, ba), (tb, bb) in zip(history, list(history)[1:]):
            ca, cb = center(ba), center(bb)
            delta = (cb[0] - ca[0], cb[1] - ca[1])
            distance = math.hypot(*delta)
            if distance < 1e-6 or (delta[0] * velocity[0] + delta[1] * velocity[1]) / (distance * speed) < 0.8:
                return None
            if distance / ((tb - ta) / NS) > speed * 2.5:
                return None
        return velocity

    def _score(self, session, box, at, *, recovery=False):
        dt = (at - session.last_ns) / NS
        if dt <= 0:
            return None
        old = session.box
        ratios = ((box[2] - box[0]) / (old[2] - old[0]), (box[3] - box[1]) / (old[3] - old[1]))
        if any(not 0.65 <= value <= 1.55 for value in ratios):
            return None
        velocity = self._velocity(session)
        if recovery:
            if not session.recoverable or dt > self.rules.motion_recovery_seconds + self.rules.recovery_confirmation_window_seconds or velocity is None:
                return None
            # A visible exit is not a recoverable occlusion, even if clothing agrees.
            if ((old[0] <= 0.02 and velocity[0] < 0) or (old[2] >= 0.98 and velocity[0] > 0)
                    or (old[1] <= 0.02 and velocity[1] < 0) or (old[3] >= 0.98 and velocity[1] > 0)):
                return None
        velocity = velocity or (0, 0)
        origin, observed = center(old), center(box)
        predicted = (origin[0] + velocity[0] * dt, origin[1] + velocity[1] * dt)
        if recovery and not all(0.02 < value < 0.98 for value in predicted):
            return None
        error = math.dist(predicted, observed)
        diagonal = math.hypot(old[2] - old[0], old[3] - old[1])
        tolerance = min(self.rules.recovery_position_tolerance if recovery else self.rules.active_position_tolerance,
                        diagonal * (0.15 if recovery else 0.5))
        if error > tolerance:
            return None
        score = 1 - 0.7 * error / tolerance - 0.15 * sum(abs(1 - r) for r in ratios)
        return score if score >= self.rules.minimum_match_score else None

    def _pairs(self, rows, candidates, scorer, *, diagnose=True):
        # Mutual unique bests with margins on BOTH sides. Unmatched is a valid
        # result; raw tracker IDs never break a tie or force an assignment.
        by_row, by_candidate = {}, {}
        for i, row in enumerate(rows):
            for session in candidates:
                score = scorer(session, row)
                if score is not None:
                    by_row.setdefault(i, []).append((score, session.session_id))
                    by_candidate.setdefault(session.session_id, []).append((score, i))
        accepted = {}
        ambiguous = set()
        for i, scores in by_row.items():
            scores.sort(reverse=True)
            score, sid = scores[0]
            peers = sorted(by_candidate[sid], reverse=True)
            if ((len(scores) > 1 and score - scores[1][0] < self.rules.match_margin)
                    or peers[0][1] != i or (len(peers) > 1 and score - peers[1][0] < self.rules.match_margin)):
                ambiguous.update(s for _, s in scores)
                if diagnose:
                    self._diagnose('rejected_ambiguous')
            else:
                accepted[i] = sid
                if diagnose:
                    self._diagnose('match_accepted', session_id=sid, score=round(score, 4))
        return accepted, ambiguous

    def _observe_zones(self, session, detection, utc, delta):
        membership = associate([detection], self.settings.zones, self.settings.rules, self.settings.position)
        for alias, (state, _, _) in membership.items():
            zone = session.zones.get(alias)
            inside = state == State.OCCUPIED
            if inside:
                if zone is None:
                    zone = session.zones[alias] = ZoneTime(utc, utc)
                elif zone.observed_inside:
                    zone.duration_ns += delta
                zone.last_seen = utc
                zone.inside, zone.observed_inside, zone.outside_count = True, True, 0
            elif zone is not None:
                # No extrapolation through ambiguous/outside observations.
                zone.observed_inside = False
                if state == State.EMPTY:
                    zone.outside_count += 1
                    if zone.outside_count >= self.rules.roi_exit_observations:
                        zone.inside = False
                else:
                    zone.outside_count = 0

    def _new(self, detection, utc, at, generation):
        if detection.tracking_only or detection.confidence < self.settings.rules.strong_confidence:
            self._diagnose('weak_session_rejected')
            return None
        if len(self.sessions) >= self.rules.max_sessions:
            lost = [s for s in self.sessions.values() if s.status == 'LOST']
            if not lost:
                self._diagnose('capacity_rejected')
                return None
            self._expire(min(lost, key=lambda s: s.last_ns), 'CAPACITY')
        session = PersonSession(str(uuid4()), self.settings.camera_id, generation, utc, utc, at, at,
                                detection.box, deque([(at, detection.box)], maxlen=self.rules.history_size), origin_box=detection.box, last_strong_ns=at)
        self.sessions[session.session_id] = session
        self._bind(session, detection, generation)
        self._observe_zones(session, detection, utc, 0)
        self._event('STARTED', session)
        return session

    def _recover(self, temporary, old, detection, at):
        # Only nonoverlapping timelines can reconcile. Candidate time is added
        # once; loss is charged only on successful, in-window recovery.
        gap = temporary.first_ns - old.last_ns
        if gap <= 0:
            return temporary
        bonus = gap if self.rules.count_lost_gap else 0
        old.accumulated_ns += temporary.accumulated_ns + bonus
        old.observed_ns += temporary.observed_ns
        for alias, previous in old.zones.items():
            if alias not in temporary.zones:
                previous.observed_inside = False
                previous.outside_count += 1
        for alias, current in temporary.zones.items():
            previous = old.zones.get(alias)
            if previous is None:
                old.zones[alias] = ZoneTime(current.first_seen, current.last_seen, current.duration_ns,
                                           current.inside, current.observed_inside, current.outside_count)
            else:
                previous.duration_ns += current.duration_ns + (bonus if previous.observed_inside and current.first_seen == temporary.first_seen else 0)
                previous.last_seen = current.last_seen
                previous.inside, previous.observed_inside = current.inside, current.observed_inside
                previous.outside_count = current.outside_count
        old.last_ns, old.last_seen, old.box = at, temporary.last_seen, temporary.box
        old.last_strong_ns, old.last_observation_strong = temporary.last_strong_ns, temporary.last_observation_strong
        old.history = temporary.history
        old.status, old.reason = 'ACTIVE', None
        # Retire the provisional row atomically; its time now belongs to old.
        temporary.merged_into = old.session_id
        temporary.accumulated_ns = 0
        temporary.observed_ns = 0
        for zone in temporary.zones.values():
            zone.duration_ns = 0
        self._expire(temporary, 'MERGED')
        self._bind(old, detection, old.generation)
        self._event('RECOVERED', old, provisional_session_id=temporary.session_id, gap_us=gap // 1000,
                    count_lost_gap=self.rules.count_lost_gap)
        return old

    def recovery_score(self, old, candidate, detection, at):
        """Shared motion gate for session recovery and shadow appearance proposals."""
        if detection.tracking_only or detection.confidence < self.settings.rules.strong_confidence:
            return None
        gap = candidate.first_ns - old.last_ns
        strong_at = old.last_strong_ns if old.last_strong_ns is not None else old.last_ns
        if gap <= 0 or candidate.first_ns - strong_at > self.rules.motion_recovery_seconds * NS:
            return None
        score = self._score(old, candidate.box, at, recovery=True)
        prior = self._velocity(old)
        if score is not None:
            origin, arrival = center(old.box), center(candidate.origin_box)
            displacement = (arrival[0] - origin[0], arrival[1] - origin[1])
            expected = math.hypot(*prior) * gap / NS
            forward = sum(d * v for d, v in zip(displacement, prior)) / math.hypot(*prior)
            if abs(1 - forward / expected) > self.rules.recovery_progress_tolerance:
                return None
        velocity = self._velocity(candidate)
        if score is not None and velocity is not None:
            if sum(a * b for a, b in zip(velocity, prior)) / (math.hypot(*velocity) * math.hypot(*prior)) < 0.8:
                return None
        return score

    def update(self, detections, utc, at, generation, unavailable=None, *, recover=True):
        self.now_ns = at
        self._velocity_cache.clear()
        changed_generation = self.generation is not None and generation != self.generation
        active = [s for s in self.sessions.values() if s.status == 'ACTIVE']
        for session in active:
            if unavailable or changed_generation or at - (session.last_strong_ns if session.last_strong_ns is not None else session.last_ns) > self.settings.rules.max_evidence_gap_seconds * NS:
                self._lose(session, unavailable or ('GENERATION_CHANGED' if changed_generation else 'EVIDENCE_GAP'),
                           block=bool(unavailable or changed_generation))
        for session in list(self.sessions.values()):
            if session.status == 'LOST':
                if changed_generation or unavailable:
                    session.recoverable = False
                    self.dirty[session.session_id] = session
                if at - session.last_ns >= self.rules.grace_period_seconds * NS:
                    self._expire(session, 'GRACE_EXPIRED')
        self.generation = generation
        if unavailable:
            return []
        active = [s for s in self.sessions.values() if s.status == 'ACTIVE']
        raw_counts = Counter(d.track_id for d in detections if d.track_id is not None)

        def active_score(session, detection):
            strong = not detection.tracking_only and detection.confidence >= self.settings.rules.strong_confidence
            continuing = (self.continuation_confidence is not None
                          and detection.confidence >= self.continuation_confidence
                          and detection.track_id is not None and raw_counts[detection.track_id] == 1
                          and detection.track_id == session.track_id)
            return self._score(session, detection.box, at) if strong or continuing else None

        pairs, ambiguous = self._pairs(detections, active, active_score)
        for session in active:
            if session.session_id not in pairs.values():
                self._lose(session, 'AMBIGUOUS' if session.session_id in ambiguous else 'DETECTION_LOST',
                           block=session.session_id in ambiguous)
        bindings = []
        for i, detection in enumerate(detections):
            session = self.sessions.get(pairs.get(i))
            if session:
                strong = not detection.tracking_only and detection.confidence >= self.settings.rules.strong_confidence
                delta = at - session.last_ns if strong and session.last_observation_strong else 0
                session.accumulated_ns += delta
                session.observed_ns += delta
                if strong:
                    self._observe_zones(session, detection, utc, delta)
                else:
                    for zone in session.zones.values():
                        zone.observed_inside, zone.outside_count = False, 0
                session.last_ns, session.box = at, detection.box
                session.history.append((at, detection.box))
                session.last_observation_strong = strong
                if strong:
                    session.last_strong_ns = at
                    session.last_seen = utc
                else:
                    self._diagnose('weak_continuation_frozen')
                self._bind(session, detection, generation)
                self.dirty[session.session_id] = session
            else:
                session = self._new(detection, utc, at, generation)
            # Duplicated raw IDs never create duplicate active mappings.
            if session and detection.track_id is not None and raw_counts[detection.track_id] > 1:
                session.track_id = None
                self._diagnose('duplicate_tracker_id')
            bindings.append((detection, session))
        if not recover:
            return bindings
        provisional = [(i, s) for i, (_, s) in enumerate(bindings) if s and at - s.first_ns <= self.rules.recovery_confirmation_window_seconds * NS]
        lost = [s for s in self.sessions.values() if s.status == 'LOST' and s.recoverable and s.generation == generation]

        def recovery_score(old, row):
            index, candidate = row
            return self.recovery_score(old, candidate, bindings[index][0], at)

        recovery_pairs, _ = self._pairs(provisional, lost, recovery_score)
        for j, (index, candidate) in enumerate(provisional):
            sid = recovery_pairs.get(j)
            if sid is None:
                candidate.candidate_id, candidate.candidate_votes = None, 0
                if lost:
                    self._diagnose('rejected_insufficient_evidence')
                continue
            if candidate.candidate_id == sid:
                candidate.candidate_votes += 1
            else:
                candidate.candidate_id, candidate.candidate_votes, candidate.candidate_since_ns = sid, 1, at
            old = self.sessions[sid]
            if (candidate.candidate_votes >= self.rules.recovery_confirm_observations
                    and at - candidate.candidate_since_ns >= self.rules.recovery_confirm_seconds * NS
                    and self._velocity(candidate) is not None):
                detection = bindings[index][0]
                bindings[index] = (detection, self._recover(candidate, old, detection, at))
        for detection, session in bindings:
            if session and detection.track_id is not None and raw_counts[detection.track_id] > 1:
                session.track_id = None
        # Raw IDs may swap while geometry stays coherent; repair the full mapping
        # together, never through a mutable tracker-ID -> timer lookup.
        return bindings

    def rows(self):
        return [self.snapshot(s) for s in self.dirty.values()]

    def snapshot(self, session):
        at = self.now_ns if self.now_ns is not None else session.last_ns
        strong_at = session.last_strong_ns if session.last_strong_ns is not None else session.first_ns
        return {'session_id': session.session_id, 'camera_id': session.camera_id, 'generation_id': session.generation,
                'first_seen_utc_us': session.first_seen, 'last_seen_utc_us': session.last_seen,
                'observed_duration_us': session.observed_ns // 1000,
                'total_elapsed_us': max(0, at - session.first_ns) // 1000,
                'absence_duration_us': max(0, at - strong_at) // 1000,
                'accumulated_duration_us': session.accumulated_ns // 1000, 'status': session.status,
                'track_id': session.track_id, 'track_lifecycle': session.track_lifecycle,
                'mapping_version': self.mapping_version, 'reason': session.reason, 'merged_into': session.merged_into,
                'matching': {'motion_recoverable': session.recoverable, 'history_samples': len(session.history),
                             'observed_duration_us': session.observed_ns // 1000},
                'zone_times': {alias: {'first_seen_utc_us': z.first_seen, 'last_seen_utc_us': z.last_seen,
                                      'presence_us': z.duration_ns // 1000, 'inside': z.inside}
                               for alias, z in session.zones.items()}}

    def checkpoint(self):
        self.dirty.clear()
        self.events.clear()

    def finish(self):
        self.sessions.clear()
        self.now_ns = None
        self._velocity_cache.clear()
        self.checkpoint()
