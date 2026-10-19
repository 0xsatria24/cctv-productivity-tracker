"""Bounded fair scheduling shared by dashboard and headless editions."""
from collections import deque
from threading import Condition
import time


class FairDetector:
    """One model resident in memory; bounded FIFO arbitration between cameras."""
    def __init__(self, detector):
        self.detector = detector
        self.condition, self.queue = Condition(), deque()
        self.high_water, self.rejected = 0, 0

    def __getattr__(self, name):
        return getattr(self.detector, name)

    def detect(self, jpeg):
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
                    self.condition.notify_all()
                    raise BlockingIOError('Antrean analisis melewati batas waktu; frame dilewati')
                self.condition.wait(remaining)
        try:
            waited = (time.perf_counter()-queued_at)*1000
            result = self.detector.detect(jpeg)
            result['scheduler_queue_ms'] = round(waited,2)
            return result
        finally:
            with self.condition:
                self.queue.popleft()
                self.condition.notify_all()

    def scheduling_snapshot(self):
        with self.condition:
            return {'capacity':18,'pending':len(self.queue),'high_water':self.high_water,'rejected':self.rejected}

