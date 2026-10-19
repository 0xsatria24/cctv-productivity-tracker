"""Bounded stage measurements and opt-in inference pacing with hysteresis."""
from collections import deque
import time


class SystemLoad:
    def __init__(self):
        try:
            import psutil
            self.psutil = psutil
            psutil.cpu_percent()
        except ImportError:
            self.psutil = None
        self.last, self.values = 0, {}

    def sample(self):
        if self.psutil is not None and time.perf_counter()-self.last >= 1:
            self.values = {'cpu_percent':self.psutil.cpu_percent(),
                           'available_mb':self.psutil.virtual_memory().available/2**20}
            self.last = time.perf_counter()
        return self.values


class Performance:
    def __init__(self, limit=120):
        self.rows = deque(maxlen=limit)
        self.processed, self.stale_dropped, self.rate_skipped = 0, 0, 0

    def record(self, **values):
        self.processed += 1
        self.rows.append(values)

    def snapshot(self):
        summary = {}
        for key in self.rows[-1] if self.rows else ():
            values = sorted(row[key] for row in self.rows if row.get(key) is not None)
            if values:
                summary[key] = {'mean':round(sum(values)/len(values),2),'p95':round(values[min(len(values)-1,int(len(values)*.95))],2),
                                'p99':round(values[min(len(values)-1,int(len(values)*.99))],2)}
        return {'processed':self.processed,'stale_dropped':self.stale_dropped,'rate_skipped':self.rate_skipped,'window':len(self.rows),'stages':summary}


class AdaptiveRate:
    def __init__(self, maximum=5, minimum=1, enabled=False):
        self.maximum, self.minimum, self.enabled = maximum,minimum,enabled
        self.fps = float(maximum)
        self.samples, self.last_change, self.healthy = 0,0,0

    @property
    def interval(self):
        return 1/self.fps

    def observe(self, cost_seconds, at, cpu_percent=None, available_mb=None):
        if not self.enabled:
            return
        self.samples += 1
        if self.samples < 8 or at-self.last_change < 5:
            return
        overloaded = cost_seconds > self.interval*.9 or cpu_percent is not None and cpu_percent > 85 or available_mb is not None and available_mb < 400
        if overloaded:
            self.fps = max(self.minimum,self.fps-1)
            self.healthy = 0; self.last_change = at
        elif cost_seconds < self.interval*.55 and (cpu_percent is None or cpu_percent < 70):
            self.healthy += 1
            if self.healthy >= 30:
                self.fps = min(self.maximum,self.fps+1)
                self.healthy = 0; self.last_change = at
        else:
            self.healthy = 0
