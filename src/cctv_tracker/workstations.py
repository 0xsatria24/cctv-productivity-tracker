"""Bounded workstation totals from measured evidence, independent of person IDs."""
from dataclasses import dataclass, field

from .domain.occupancy import Observation, State, ZoneAccumulator
from .workstation_engine import workstation_observations


@dataclass
class WorkstationClock:
    accumulator: ZoneAccumulator
    totals: dict = field(default_factory=lambda: {state: 0 for state in State})
    unique_media: bool = False
    covered: list = field(default_factory=list)
    media_intervals: list = field(default_factory=list)

    def remember(self, start, end, state):
        # Keep the first measured classification, including on overlapping replays.
        cursor, added = start, []
        for left, right, _ in self.media_intervals:
            if right <= cursor:
                continue
            if left >= end:
                break
            if left > cursor:
                added.append((cursor, min(left, end), state))
            cursor = max(cursor, right)
        if cursor < end:
            added.append((cursor, end, state))
        if not added:
            return
        merged = []
        for left, right, value in sorted([*self.media_intervals, *added]):
            if merged and left == merged[-1][1] and value == merged[-1][2]:
                merged[-1] = (merged[-1][0], right, value)
            else:
                merged.append((left, right, value))
        self.media_intervals = merged

    def claim(self, start, end):
        remaining = end-start
        for left, right in self.covered:
            remaining -= max(0, min(end, right)-max(start, left))
        merged = []
        for left, right in sorted([*self.covered, (start, end)]):
            if merged and left <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], right))
            else:
                merged.append((left, right))
        self.covered = merged
        return max(0, remaining)

    def feed(self, observation):
        if self.unique_media and self.accumulator.last and observation.generation != self.accumulator.last.generation:
            self.accumulator = ZoneAccumulator(observation.utc_us, self.accumulator.rules)
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
            self.totals[state] += self.claim(previous.utc_us, observation.utc_us) if self.unique_media else delta
            if self.unique_media:
                self.remember(previous.utc_us, observation.utc_us, state)
        self.accumulator.checkpoint()

    def snapshot(self, zone):
        total = sum(self.totals.values())
        known = self.totals[State.OCCUPIED] + self.totals[State.EMPTY]
        current = self.accumulator.current
        return {'zone_id': zone.id, 'name': zone.name, 'state': current.state,
                'count': current.count, 'reason': current.reason,
                'occupied_us': self.totals[State.OCCUPIED], 'empty_us': self.totals[State.EMPTY],
                'unknown_us': self.totals[State.UNKNOWN], 'observed_us': total,
                'coverage': known / total if total else None,
                **({'media_intervals': [list(span) for span in self.media_intervals],
                    'media_intervals_complete': sum(right-left for left, right, _ in self.media_intervals) == total}
                   if self.unique_media else {})}


class WorkstationTimeline:
    def __init__(self, settings, *, unique_media=False):
        self.settings = settings
        self.clocks = {}
        self.unique_media = unique_media
        self.history = []

    def reconfigure(self, settings):
        previous = {zone.id: zone for zone in self.settings.zones}
        current = {zone.id: zone for zone in settings.zones}
        changed = [sid for sid in self.clocks if sid not in current or previous[sid].polygon != current[sid].polygon
                   or self.settings.position != settings.position]
        if len(self.history)+len(changed) > 256:
            raise ValueError('Riwayat area penuh; ekspor hasil dan gunakan sesi baru')
        for sid, clock in list(self.clocks.items()):
            if (sid not in current or previous[sid].polygon != current[sid].polygon
                    or self.settings.position != settings.position):
                self.history.append({**clock.snapshot(previous[sid]), 'reason': 'AREA_CHANGED'})
                del self.clocks[sid]
        self.settings = settings

    def snapshot(self):
        return [self.clocks[z.id].snapshot(z) for z in self.settings.zones if z.id in self.clocks]

    def export_state(self):
        return {'clocks': {sid: {'totals': dict(clock.totals), 'covered': clock.covered,
                                'media_intervals': clock.media_intervals}
                           for sid, clock in self.clocks.items()}, 'history': self.history}

    def restore(self, saved):
        valid_ids = {zone.id for zone in self.settings.zones}
        for sid, record in saved.get('clocks', {}).items():
            if sid not in valid_ids:
                continue
            totals = record['totals']
            covered = record['covered']
            if (set(totals) != set(State) or any(type(v) is not int or v < 0 for v in totals.values())
                    or not isinstance(covered, list) or len(covered) > 10000):
                raise ValueError('Invalid saved workstation totals')
            end = -1
            for left, right in covered:
                if (type(left) is not int or type(right) is not int or left < 0
                        or left >= right or left <= end or right > 2_592_000_000_000):
                    raise ValueError('Invalid saved media coverage')
                end = right
            if sum(totals.values()) != sum(right-left for left, right in covered):
                raise ValueError('Saved coverage does not match totals')
            intervals = record.get('media_intervals', [])
            if not isinstance(intervals, list) or len(intervals) > 10000:
                raise ValueError('Invalid saved playback intervals')
            end, coverage_index = -1, 0
            for span in intervals:
                if not isinstance(span, (list, tuple)) or len(span) != 3:
                    raise ValueError('Invalid saved playback interval')
                left, right, state = span
                if (type(left) is not int or type(right) is not int or left < 0 or left >= right
                        or left < end or state not in set(State)):
                    raise ValueError('Invalid saved playback interval')
                while coverage_index < len(covered) and covered[coverage_index][1] <= left:
                    coverage_index += 1
                if (coverage_index == len(covered) or covered[coverage_index][0] > left
                        or covered[coverage_index][1] < right):
                    raise ValueError('Playback interval is outside saved coverage')
                end = right
            self.clocks[sid] = WorkstationClock(ZoneAccumulator(0, self.settings.rules),
                                               {State(k): v for k, v in totals.items()}, True,
                                               [tuple(pair) for pair in covered], [tuple(span) for span in intervals])
        history = saved.get('history', [])
        if not isinstance(history, list) or len(history) > 256:
            raise ValueError('Invalid saved area history')
        for row in history:
            if (not isinstance(row, dict) or not isinstance(row.get('zone_id'), str) or not isinstance(row.get('name'), str)
                    or any(type(row.get(key)) is not int or row[key] < 0 for key in ('occupied_us','empty_us','unknown_us','observed_us'))
                    or row['occupied_us']+row['empty_us']+row['unknown_us'] != row['observed_us']):
                raise ValueError('Invalid saved area history totals')
        self.history = history

    def update(self, detections, frame):
        observations = workstation_observations(detections, self.settings)
        at = round(frame.media_time * 1e6)
        for zone in self.settings.zones:
            clock = self.clocks.setdefault(zone.id, WorkstationClock(ZoneAccumulator(at, self.settings.rules), unique_media=self.unique_media))
            state, count, reason = observations[zone.id]
            clock.feed(Observation(at, round(frame.media_time * 1e9), frame.sequence,
                                   str(frame.generation), state, count, reason))
        return [self.clocks[zone.id].snapshot(zone) for zone in self.settings.zones]
