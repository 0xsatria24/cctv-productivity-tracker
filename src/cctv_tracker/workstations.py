"""Bounded workstation totals from measured evidence, independent of person IDs."""
from dataclasses import dataclass, field

from .domain.occupancy import Observation, State, ZoneAccumulator
from .vision import associate


@dataclass
class WorkstationClock:
    accumulator: ZoneAccumulator
    totals: dict = field(default_factory=lambda: {state: 0 for state in State})

    def feed(self, observation):
        previous = self.accumulator.last
        previous_state = self.accumulator.current.state
        self.accumulator.feed(observation)
        current = self.accumulator.current
        if previous:
            delta = observation.utc_us - previous.utc_us
            continuous = (observation.generation == previous.generation
                          and observation.monotonic_ns - previous.monotonic_ns <= self.accumulator.rules.max_evidence_gap_seconds * 1e9)
            # Both ends must confirm the same state. Missing/ambiguous gaps never earn time.
            state = current.state if (continuous and previous_state == current.state
                                      and previous.evidence == observation.evidence == current.state) else State.UNKNOWN
            self.totals[state] += delta
        self.accumulator.checkpoint()

    def snapshot(self, zone):
        total = sum(self.totals.values())
        known = self.totals[State.OCCUPIED] + self.totals[State.EMPTY]
        current = self.accumulator.current
        return {'zone_id': zone.id, 'name': zone.name, 'state': current.state,
                'count': current.count, 'reason': current.reason,
                'occupied_us': self.totals[State.OCCUPIED], 'empty_us': self.totals[State.EMPTY],
                'unknown_us': self.totals[State.UNKNOWN], 'observed_us': total,
                'coverage': known / total if total else None}


class WorkstationTimeline:
    def __init__(self, settings):
        self.settings = settings
        self.clocks = {}

    def update(self, detections, frame):
        observations = associate(detections, self.settings.zones, self.settings.rules, self.settings.position)
        at = round(frame.media_time * 1e6)
        for zone in self.settings.zones:
            clock = self.clocks.setdefault(zone.id, WorkstationClock(ZoneAccumulator(at, self.settings.rules)))
            state, count, reason = observations[zone.id]
            clock.feed(Observation(at, round(frame.media_time * 1e9), frame.sequence,
                                   str(frame.generation), state, count, reason))
        return [self.clocks[zone.id].snapshot(zone) for zone in self.settings.zones]
