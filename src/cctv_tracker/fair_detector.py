"""Bounded fair scheduling shared by dashboard and headless editions."""
from collections import deque
from contextlib import contextmanager
from threading import Condition
import time


class FairDetector:
    """One model resident in memory; bounded FIFO arbitration between cameras."""
    def __init__(self, detector):
        self.detector = detector
        self.condition, self.queue = Condition(), deque()
        self.high_water, self.rejected, self.refreshed = 0, 0, 0

    def __getattr__(self, name):
        return getattr(self.detector, name)

    @contextmanager
    def _turn(self):
        queued_at = time.perf_counter()
        ticket, deadline = object(), time.monotonic() + 2
        with self.condition:
            if len(self.queue) >= 18:
                self.rejected += 1
                raise BlockingIOError('Antrean analisis penuh; frame dilewati')
            self.queue.append(ticket)
            self.high_water = max(self.high_water,len(self.queue))
            while self.queue[0] is not ticket:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self.queue.remove(ticket)
                    self.rejected += 1
                    self.condition.notify_all()
                    raise BlockingIOError('Antrean analisis melewati batas waktu; frame dilewati')
                self.condition.wait(remaining)
        try:
            waited = (time.perf_counter()-queued_at)*1000
            yield waited
        finally:
            with self.condition:
                self.queue.popleft()
                self.condition.notify_all()

    def detect(self, jpeg):
        with self._turn() as waited:
            result = self.detector.detect(jpeg)
            result['scheduler_queue_ms'] = round(waited,2)
            return result

    def detect_latest(self, item, refresh, max_age_seconds, *, stop_event=None, minimum_monotonic_ns=0):
        """Select again AFTER waiting for the model. Never infer an old backlog."""
        with self._turn() as waited:
            if stop_event and stop_event.is_set():
                raise BlockingIOError('Permintaan inferensi dibatalkan')
            newer = refresh() if refresh else None
            if newer and newer.get('error'):
                raise ValueError('Kamera terputus saat menunggu inferensi')
            if newer and not newer.get('error') and newer['monotonic_ns'] > item['monotonic_ns']:
                item = newer
                self.refreshed += 1
            if item['monotonic_ns'] <= minimum_monotonic_ns or not 0 <= time.perf_counter_ns()-item['monotonic_ns'] <= max_age_seconds*1e9:
                raise ValueError('Frame stale setelah antrean; menunggu frame terbaru')
            result = self.detector.detect(item['jpeg'])
            if stop_event and stop_event.is_set():
                raise BlockingIOError('Hasil inferensi dibatalkan')
            result['scheduler_queue_ms'] = round(waited,2)
            return result,item

    def scheduling_snapshot(self):
        with self.condition:
            return {'capacity':18,'pending':len(self.queue),'high_water':self.high_water,'rejected':self.rejected,'refreshed_frames':self.refreshed}
