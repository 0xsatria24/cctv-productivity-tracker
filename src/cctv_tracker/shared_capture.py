"""Read-only latest-frame subscriber; closing it never stops the preview owner."""
from types import SimpleNamespace
import time


class SharedPreviewCapture:
    def __init__(self, preview):
        self.preview, self.closed, self.last = preview, False, None
        self.started = time.perf_counter()
        self.minimum_ns = time.perf_counter_ns()
        self.process = SimpleNamespace(is_alive=lambda: not self.closed and preview._thread.is_alive())

    def read(self, timeout=.2):
        deadline = time.perf_counter()+timeout
        while not self.closed:
            item = self.preview.capture_snapshot()
            if item and item['monotonic_ns'] >= self.minimum_ns and item['monotonic_ns'] != self.last:
                self.last = item['monotonic_ns']
                return item
            remaining = deadline-time.perf_counter()
            if remaining <= 0:
                return None
            self.preview._stop.wait(min(.01,remaining))
        return None

    def close(self):
        self.closed = True
