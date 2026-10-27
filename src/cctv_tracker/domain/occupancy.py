from dataclasses import dataclass, replace
from enum import StrEnum

EVIDENCE_POLICY_REVISION = 'last-supporting-sample-v2'


class State(StrEnum):
    OCCUPIED = "OCCUPIED"
    EMPTY = "EMPTY"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class Observation:
    utc_us: int
    monotonic_ns: int
    frame_seq: int
    generation: str
    evidence: State
    count: int | None
    reason: str | None = None

    def __post_init__(self):
        if self.utc_us < 0 or self.monotonic_ns < 0 or self.frame_seq < 1 or not self.generation:
            raise ValueError("Invalid observation envelope")
        if self.evidence == State.EMPTY and self.count != 0:
            raise ValueError("Empty evidence requires zero count")
        if self.evidence == State.OCCUPIED and self.count is not None and self.count < 1:
            raise ValueError("Occupied count must be positive or unavailable")
        if self.evidence == State.UNKNOWN and (self.count is not None or not self.reason):
            raise ValueError("Unknown requires a reason and unavailable count")


@dataclass(frozen=True)
class Interval:
    state: State
    start: int
    until: int
    count: int | None
    reason: str | None
    closed: bool = False


class ZoneAccumulator:
    """Confirmation is unknown, with no historical backdating or predicted presence."""

    def __init__(self, start: int, rules):
        self.rules = rules
        self.closed: list[Interval] = []
        self.current = Interval(State.UNKNOWN, start, start, None, "STARTUP")
        self.last: Observation | None = None
        self.candidate: tuple[State, int] | None = None

    def _transition(self, at, state, count, reason):
        old = replace(self.current, until=at, closed=True)
        if old.until > old.start:
            self.closed.append(old)
        self.current = Interval(state, at, at, count, reason)

    def feed(self, obs: Observation):
        previous = self.last
        if previous and obs.generation == previous.generation and obs.frame_seq <= previous.frame_seq:
            raise ValueError("Duplicate or out-of-order observation")
        if previous and (obs.utc_us < previous.utc_us or obs.monotonic_ns <= previous.monotonic_ns):
            raise ValueError("Clock moved backwards or monotonic observation did not advance")
        if obs.utc_us < self.current.start:
            raise ValueError("Observation predates monitoring")
        broken = previous and (obs.generation != previous.generation or obs.monotonic_ns - previous.monotonic_ns > self.rules.max_evidence_gap_seconds * 1e9)
        if previous and abs((obs.utc_us - previous.utc_us) * 1000 - (obs.monotonic_ns - previous.monotonic_ns)) > 1e9:
            obs = replace(obs, evidence=State.UNKNOWN, count=None, reason="CLOCK_DISCONTINUITY")
        if broken or obs.evidence == State.UNKNOWN:
            reason = obs.reason or "FRAME_STALE"
            if self.current.state != State.UNKNOWN:
                self._transition(self.current.until, State.UNKNOWN, None, reason)
            elif self.current.reason != reason:
                self._transition(self.current.until, State.UNKNOWN, None, reason)
            self.current = replace(self.current, until=obs.utc_us, reason=reason)
            self.candidate = None
        else:
            if self.current.state != State.UNKNOWN and self.current.state != obs.evidence:
                # Contradictory evidence ends the prior state at its last supporting sample.
                self._transition(self.current.until, State.UNKNOWN, None, 'PENDING_CONFIRMATION')
            self.current = replace(self.current, until=obs.utc_us)
        if obs.evidence != State.UNKNOWN:
            if self.current.state == obs.evidence:
                self.candidate = None
                if self.current.count != obs.count:
                    self._transition(obs.utc_us, obs.evidence, obs.count, None)
            else:
                if self.current.state != State.UNKNOWN:
                    self._transition(obs.utc_us, State.UNKNOWN, None, "PENDING_CONFIRMATION")
                elif self.current.reason != "PENDING_CONFIRMATION":
                    self._transition(obs.utc_us, State.UNKNOWN, None, "PENDING_CONFIRMATION")
                self.current = replace(self.current, reason="PENDING_CONFIRMATION")
                if self.candidate is None or self.candidate[0] != obs.evidence:
                    self.candidate = (obs.evidence, obs.monotonic_ns)
                seconds = self.rules.occupied_confirm_seconds if obs.evidence == State.OCCUPIED else self.rules.empty_confirm_seconds
                if obs.monotonic_ns - self.candidate[1] >= seconds * 1e9:
                    self._transition(obs.utc_us, obs.evidence, obs.count, None)
                    self.candidate = None
        self.last = obs

    def snapshot(self):
        return (*self.closed, self.current)

    def checkpoint(self):
        """Called only after the corresponding transaction commits."""
        self.closed.clear()


def summarize(intervals, start, end):
    if end <= start:
        raise ValueError("Report end must be after start")
    totals = {State.OCCUPIED: 0, State.EMPTY: 0}
    previous_until = start
    for row in sorted(intervals, key=lambda x: x.start):
        left, right = max(start, row.start), min(end, row.until)
        if right <= left:
            continue
        if left < previous_until:
            raise ValueError("Overlapping intervals")
        previous_until = right
        if row.state in totals:
            totals[row.state] += right - left
    p, a, t = totals[State.OCCUPIED], totals[State.EMPTY], end - start
    return {"eligible_us": t, "occupied_us": p, "empty_us": a, "unknown_us": t - p - a,
            "utilization": p / (p + a) if p + a else None, "coverage": (p + a) / t}
