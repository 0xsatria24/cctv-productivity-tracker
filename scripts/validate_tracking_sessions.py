"""Synthetic tracking metrics and local latency/heap benchmark, no camera/model.

Run with the project venv. Baseline is HEAD's Pipeline with the same installed
tracker, SQLite settings and detector fixtures, isolating session-management cost.
"""
import argparse
from contextlib import closing
import gc
import json
import math
from pathlib import Path
import platform
import statistics
import subprocess
import time
import tracemalloc
from types import ModuleType
from uuid import uuid4

from cctv_tracker.config import Settings, SessionRules, Zone
from cctv_tracker.persistence import Database
from cctv_tracker.pipeline import Pipeline
from cctv_tracker.sessions import SessionManager
from cctv_tracker.vision import Detection

ROOT = Path(__file__).resolve().parents[1]


def config(path, count_lost_gap=False):
    return Settings(database=path, sessions=SessionRules(count_lost_gap=count_lost_gap),
                    zones=(Zone('desk', 'Desk', ((0, 0), (1, 0), (1, 1), (0, 1))),))


def person(x, track='A', y=0.35):
    return Detection((x, y, x + 0.1, y + 0.25), 0.95, track)


def a(t, track='A'):
    return person(0.05 + 0.02 * t, track)


class Probe:
    def __init__(self, count_lost_gap=False):
        self.manager = SessionManager(config(ROOT / 'runtime/unused.sqlite3', count_lost_gap))
        self.observations, self.aliases = [], {}
        self.last = []

    def feed(self, t, labeled=(), *, generation='camera', unavailable=None):
        self.last = self.manager.update([d for _, d in labeled], 1_000_000 + round(t * 1e6),
                                        round(t * 1e9), generation, unavailable)
        for (label, _), (_, session) in zip(labeled, self.last):
            if session:
                self.observations.append((label, session.session_id))
        for row in self.manager.rows():
            if row['merged_into']:
                self.aliases[row['session_id']] = row['merged_into']
        self.manager.checkpoint()

    def prime(self):
        for step in range(76):
            self.feed(step / 5, [('A', a(step / 5))])

    def result(self):
        def canonical(sid):
            while sid in self.aliases:
                sid = self.aliases[sid]
            return sid
        owners, seen, previous = {}, {}, {}
        switches = 0
        for label, sid in self.observations:
            sid = canonical(sid)
            owners.setdefault(sid, set()).add(label)
            seen.setdefault(label, set()).add(sid)
            switches += int(sid in previous and previous[sid] != label)
            previous[sid] = label
        return {'identity_switches': switches, 'false_session_merges': sum(len(v) > 1 for v in owners.values()),
                'persistent_fragments_beyond_first': sum(max(0, len(v) - 1) for v in seen.values()),
                'sessions_per_person': {k: len(v) for k, v in seen.items()},
                'last_durations_seconds': [s.accumulated_ns / 1e9 for _, s in self.last if s],
                'diagnostics': dict(self.manager.metrics)}


def quality():
    results = {}
    for count in (False, True):
        p = Probe(count); p.prime(); p.feed(15.2)
        for t in (18, 18.1, 18.2):
            p.feed(t, [('A', a(t, 'changed'))])
        results[f'15s_loss3s_count_gap_{count}'] = p.result()
    p = Probe(); p.prime(); p.feed(15.2, [('A', a(15.2, 'changed'))])
    results['continuous_track_id_change'] = p.result()
    p = Probe(); p.prime(); p.feed(15.2)
    for step in range(77, 90):
        p.feed(step / 5, [('B', a(15, 'A'))])
    results['B_at_last_A_position_reused_id'] = p.result()
    for t in (18, 18.1, 18.2):
        p.feed(t, [('B', a(15, 'A')), ('A', a(t, 'new-track'))])
    results['A_returns_while_B_present'] = p.result()
    p = Probe(); p.prime(); p.feed(15.2)
    for t in (15.4, 15.6, 15.8, 16, 16.2):
        p.feed(t, [('B', person(0.35 + 0.02 * (t - 15.4), 'A'))])
    results['B_at_last_A_box_then_same_direction_and_speed'] = p.result()
    p = Probe()
    for step in range(27):
        t = step / 4
        p.feed(t, [('A', person(0.1 + 0.08 * t, '1' if t < 3.75 else '2')),
                   ('B', person(0.7 - 0.08 * t, '2' if t < 3.75 else '1'))])
    results['crossing_full_occlusion_swapped_ids'] = p.result()
    p = Probe()
    for step in range(11):
        p.feed(step / 5, [('A', person(0.3))])
    p.feed(2.2)
    for t in (2.4, 2.6, 2.8):
        p.feed(t, [('B', person(0.3))])
    results['similar_stationary_replacement'] = p.result()
    p = Probe(); p.prime(); p.feed(15.2); p.feed(25)
    p.feed(25.2, [('A', a(25.2))])
    results['expiration_starts_new_session'] = p.result()
    p = Probe()
    for step in range(11):
        p.feed(step / 5, [('A', person(0.3))])
    p.feed(2.2)
    for t in (2.4, 2.6, 2.8):
        p.feed(t, [('A', person(0.3))])
    results['insufficient_motion_same_person_splits'] = p.result()
    p = Probe()
    for t in (0, 0.13, 0.7, 1.2):
        p.feed(t, [('A', person(0.2))])
    p.feed(1.4, unavailable='CAMERA_OFFLINE')
    p.feed(2, [('A', person(0.2))], generation='reconnected')
    results['variable_fps_offline_reconnect'] = p.result()
    assert all(row['false_session_merges'] == row['identity_switches'] == 0 for row in results.values())
    return results


def crowd(frame, people=16):
    offset = 0.002 * math.sin(frame / 20)
    return [Detection((0.05 + (i % 4) * 0.23 + offset, 0.04 + (i // 4) * 0.23,
                       0.13 + (i % 4) * 0.23 + offset, 0.17 + (i // 4) * 0.23), 0.95)
            for i in range(people)]


def summary(samples):
    ordered = sorted(samples)
    return {'median_ms': round(statistics.median(samples), 4),
            'p95_ms': round(ordered[min(len(ordered) - 1, math.ceil(len(ordered) * 0.95) - 1)], 4)}


def manager_benchmark(frames):
    manager = SessionManager(config(ROOT / 'runtime/unused.sqlite3'))
    samples = []
    for i in range(frames + 20):
        detections = crowd(i)
        start = time.perf_counter_ns()
        manager.update(detections, 1_000_000 + i * 200_000, i * 200_000_000, 'camera')
        manager.checkpoint()
        if i >= 20:
            samples.append((time.perf_counter_ns() - start) / 1e6)
    gc.collect()
    tracemalloc.start()
    manager = SessionManager(config(ROOT / 'runtime/unused.sqlite3'))
    i = -1
    retained = []
    for phase in range(2):
        for j in range(frames):
            i += 1
            manager.update(crowd(i), 1_000_000 + i * 200_000, i * 200_000_000, 'camera')
            manager.checkpoint()
        gc.collect()
        retained.append(tracemalloc.get_traced_memory()[0])
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return {**summary(samples), 'people': 16, 'measured_frames': frames,
            'retained_python_heap_bytes_by_phase': retained, 'peak_python_heap_bytes': peak,
            'heap_measurement': 'fresh manager Python allocations; excludes native decoder/model and process RSS',
            'retained_sessions': len(manager.sessions), 'history_samples': sum(len(s.history) for s in manager.sessions.values())}


def pipeline_benchmark(pipeline_class, path, frames):
    cfg = config(path)
    with closing(Database(path)) as db:
        pipeline = pipeline_class(cfg, db, 1_000_000, 'SYNTHETIC_REPLAY', 'a' * 64, {})
        samples = []
        try:
            for i in range(frames + 10):
                detections = crowd(i)
                started = time.perf_counter_ns()
                pipeline.feed(detections, 1_000_000 + i * 200_000, i * 200_000_000, i + 1, 'camera')
                if i >= 10:
                    samples.append((time.perf_counter_ns() - started) / 1e6)
        finally:
            pipeline.finish()
    return {**summary(samples), 'people': 16, 'measured_frames': frames}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--frames', type=int, default=500)
    parser.add_argument('--pipeline-frames', type=int, default=80)
    parser.add_argument('--output', type=Path, default=ROOT / 'runtime/tracking-session-validation.json')
    args = parser.parse_args()
    if args.frames < 10 or args.pipeline_frames < 10:
        parser.error('Use at least 10 frames')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    source = subprocess.run(['git', 'show', 'HEAD:src/cctv_tracker/pipeline.py'], cwd=ROOT,
                            capture_output=True, text=True, check=True).stdout
    baseline = ModuleType('cctv_tracker._session_benchmark_baseline')
    baseline.__package__ = 'cctv_tracker'
    exec(compile(source, '<HEAD pipeline baseline>', 'exec'), baseline.__dict__)
    identifier = uuid4().hex[:8]
    baseline_timing = pipeline_benchmark(baseline.Pipeline, args.output.parent / f'baseline-{identifier}.sqlite3', args.pipeline_frames)
    current_timing = pipeline_benchmark(Pipeline, args.output.parent / f'sessions-{identifier}.sqlite3', args.pipeline_frames)
    report = {'fixture_notice': 'Synthetic detections only; no physical camera, decoder, model throughput or field identity accuracy.',
              'environment': {'python': platform.python_version(), 'platform': platform.platform(),
                              'baseline_revision': subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()},
              'quality': quality(), 'manager': manager_benchmark(args.frames),
              'pipeline_baseline': baseline_timing, 'pipeline_sessions': current_timing,
              'pipeline_delta_median_ms': round(current_timing['median_ms'] - baseline_timing['median_ms'], 4)}
    args.output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
