"""Bounded, per-source arbitration for one resident detector."""
from collections import OrderedDict
from contextlib import contextmanager
from dataclasses import dataclass
import math
from threading import Condition
import time

from .fair_detector import FairDetector


@dataclass(frozen=True)
class SchedulingRules:
    queue_capacity: int = 64
    max_streams: int = 128
    max_wait_seconds: float = 2

    def __post_init__(self):
        if type(self.queue_capacity) is not int or not 1 <= self.queue_capacity <= 256:
            raise ValueError('Scheduler queue capacity must be between 1 and 256')
        if type(self.max_streams) is not int or not self.queue_capacity <= self.max_streams <= 1024:
            raise ValueError('Scheduler stream capacity must cover its queue, up to 1024')
        if isinstance(self.max_wait_seconds, bool) or not math.isfinite(self.max_wait_seconds) or not 0 < self.max_wait_seconds <= 30:
            raise ValueError('Scheduler wait limit must be positive and at most 30 seconds')


class InferenceScheduler:
    def __init__(self, detector, rules=None):
        self.detector, self.rules = detector, rules or SchedulingRules()
        self.condition = Condition()
        self.pending, self.streams = OrderedDict(), OrderedDict()
        self.active = None
        self.closed = False
        self.totals = dict(completed=0, failed=0, rejected=0, expired=0, cancelled=0, refreshed=0, high_water=0)

    def bind(self, source_id, *, max_fps=None):
        if not isinstance(source_id, str) or not 1 <= len(source_id) <= 128:
            raise ValueError('Invalid inference source ID')
        if max_fps is not None and (isinstance(max_fps, bool) or not math.isfinite(max_fps) or not 0 < max_fps <= 30):
            raise ValueError('Invalid inference frame rate')
        return ScheduledDetector(self, source_id, max_fps)

    def _stream(self, source):
        if source not in self.streams:
            if len(self.streams) >= self.rules.max_streams:
                disposable = next((key for key in self.streams if key not in self.pending and key != self.active), None)
                if disposable is None:
                    self.totals['rejected'] += 1
                    raise BlockingIOError('Kapasitas sumber inferensi penuh')
                del self.streams[disposable]
            self.streams[source] = dict(completed=0, failed=0, rejected=0, expired=0, cancelled=0, refreshed=0,
                                        last_started=0., last_completed=0., queue_ms=0., service_ms=0.)
        self.streams.move_to_end(source)
        return self.streams[source]

    def _count(self, source, metric):
        self.totals[metric] += 1
        self.streams[source][metric] += 1

    @contextmanager
    def turn(self, lane, stop_event=None):
        source = lane.source_id
        enqueued = time.monotonic()
        deadline = enqueued + self.rules.max_wait_seconds
        ticket = object()
        with self.condition:
            if self.closed or lane.closed:
                raise BlockingIOError('Scheduler inferensi ditutup')
            stats = self._stream(source)
            if source == self.active or source in self.pending or len(self.pending) >= self.rules.queue_capacity:
                self._count(source, 'rejected')
                raise BlockingIOError('Sumber masih diproses atau antrean inferensi penuh; kirim frame terbaru')
            # FIFO among eligible sources. A camera waiting for its FPS slot never blocks another.
            ready_at = stats['last_started'] + (1 / lane.max_fps if lane.max_fps else 0)
            self.pending[source] = (ticket, ready_at)
            self.totals['high_water'] = max(self.totals['high_water'], len(self.pending))
            try:
                while True:
                    now = time.monotonic()
                    if self.closed or lane.closed or (stop_event and stop_event.is_set()):
                        self._count(source, 'cancelled')
                        raise BlockingIOError('Permintaan inferensi dibatalkan')
                    if now >= deadline:
                        self._count(source, 'expired')
                        raise BlockingIOError('Antrean inferensi melewati batas waktu; kirim frame terbaru')
                    eligible = next((key for key, (_, at) in self.pending.items() if at <= now), None)
                    if self.active is None and eligible == source:
                        del self.pending[source]
                        self.active = source
                        stats['last_started'], stats['queue_ms'] = now, round((now - enqueued)*1000, 2)
                        break
                    self.condition.wait(min(0.05, deadline - now))
            except BaseException:
                if self.pending.get(source, (None,))[0] is ticket:
                    del self.pending[source]
                self.condition.notify_all()
                raise
        try:
            yield stats['queue_ms']
            if self.closed or lane.closed or (stop_event and stop_event.is_set()):
                with self.condition:
                    self._count(source, 'cancelled')
                raise BlockingIOError('Hasil inferensi dibatalkan; tidak menjadi bukti')
        finally:
            with self.condition:
                self.active = None
                self.condition.notify_all()

    def snapshot(self, source_id=None):
        with self.condition:
            now = time.monotonic()
            if source_id is None:
                selected = self.streams.items()
            else:
                selected = ((source_id, self.streams[source_id]),) if source_id in self.streams else ()
            return {'policy': 'fifo-per-source', 'closed': self.closed, 'active_source': self.active,
                    'queue_capacity': self.rules.queue_capacity, 'max_streams': self.rules.max_streams,
                    'max_wait_seconds': self.rules.max_wait_seconds, 'pending': len(self.pending),
                    **self.totals,
                    'streams': {key: {**{k: v for k, v in stats.items() if k not in {'last_started', 'last_completed'}},
                                      'pending': key in self.pending, 'active': key == self.active,
                                      'last_completed_age_seconds': round(now - stats['last_completed'], 3) if stats['last_completed'] else None}
                                for key, stats in selected}}

    def close(self, timeout=2):
        with self.condition:
            self.closed = True
            self.condition.notify_all()
            self.condition.wait_for(lambda: self.active is None, timeout=timeout)


class ScheduledDetector:
    def __init__(self, scheduler, source_id, max_fps):
        self.scheduler, self.source_id, self.max_fps = scheduler, source_id, max_fps
        self.closed = False

    def __getattr__(self, name):
        return getattr(self.scheduler.detector, name)

    def _detect(self, jpeg, queue_ms):
        started = time.monotonic()
        try:
            result = dict(self.scheduler.detector.detect(jpeg))
        except Exception:
            with self.scheduler.condition:
                self.scheduler._count(self.source_id, 'failed')
            raise
        with self.scheduler.condition:
            self.scheduler._count(self.source_id, 'completed')
            stats = self.scheduler.streams[self.source_id]
            stats.update(last_completed=time.monotonic(), service_ms=round((time.monotonic()-started)*1000, 2))
        return {**result, 'scheduler_queue_ms': queue_ms, 'scheduler': {'source_id': self.source_id, 'queue_ms': queue_ms,
                                      'service_ms': stats['service_ms'], 'policy': 'fifo-per-source'}}

    def detect(self, jpeg):
        with self.scheduler.turn(self) as queue_ms:
            result = self._detect(jpeg, queue_ms)
        return result

    def detect_latest(self, item, refresh, max_age_seconds, *, stop_event=None, minimum_monotonic_ns=0):
        with self.scheduler.turn(self, stop_event) as queue_ms:
            newer = refresh() if refresh else None
            if newer and newer.get('error'):
                raise ValueError('Kamera terputus saat menunggu inferensi')
            if newer and newer.get('jpeg') and newer['monotonic_ns'] > item['monotonic_ns']:
                item = newer
                with self.scheduler.condition:
                    self.scheduler._count(self.source_id, 'refreshed')
            age = (time.perf_counter_ns() - item['monotonic_ns']) / 1e9
            if item['monotonic_ns'] <= minimum_monotonic_ns or not 0 <= age <= max_age_seconds:
                with self.scheduler.condition:
                    self.scheduler._count(self.source_id, 'expired')
                raise ValueError('Frame stale setelah antrean; kirim frame terbaru')
            result = self._detect(item['jpeg'], queue_ms)
            if (time.perf_counter_ns() - item['monotonic_ns']) / 1e9 > max_age_seconds:
                with self.scheduler.condition:
                    self.scheduler._count(self.source_id, 'expired')
                raise ValueError('Inferensi melewati umur frame; hasil tidak menjadi bukti')
        return result, item

    def scheduling_snapshot(self):
        return self.scheduler.snapshot(self.source_id)

    def close(self):
        with self.scheduler.condition:
            self.closed = True
            self.scheduler.condition.notify_all()
