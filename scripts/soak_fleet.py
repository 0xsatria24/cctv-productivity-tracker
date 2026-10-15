"""Bounded multi-camera soak with simulated capture, real accounting, optional real model.

This is not a physical RTSP/camera certification. Every output states its input mode.
"""
import argparse
from contextlib import closing
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import platform
import signal
import statistics
from threading import Event, active_count
import time
from types import SimpleNamespace

from cctv_tracker.config import Settings
from cctv_tracker.fleet import CameraFleet, FairDetector
from cctv_tracker.persistence import Database
from cctv_tracker.secure_store import atomic_write


def rss_mb():
    if os.name == 'nt':
        class Counters(ctypes.Structure):
            _fields_ = [('cb', wintypes.DWORD), ('faults', wintypes.DWORD)] + [(n, ctypes.c_size_t) for n in ('peak_rss', 'rss', 'peak_pool', 'pool', 'peak_nonpool', 'nonpool', 'pagefile', 'peak_pagefile')]
        value = Counters(); value.cb = ctypes.sizeof(value)
        kernel = ctypes.WinDLL('kernel32'); kernel.GetCurrentProcess.restype = wintypes.HANDLE
        psapi = ctypes.WinDLL('psapi'); psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
        if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(value), value.cb):
            raise RuntimeError('Memory measurement unavailable')
        return value.rss / 1048576
    return int(Path('/proc/self/statm').read_text().split()[1]) * os.sysconf('SC_PAGE_SIZE') / 1048576


class FixtureDetector:
    sha = 'f' * 64
    manifest = {'source': 'SYNTHETIC_DETECTIONS', 'license': 'local fixture'}
    def detect(self, jpeg):
        rows = [] if jpeg == b'empty' else [{'box': [.2, .2, .6, .9], 'confidence': .95}]
        return {'width': 320, 'height': 240, 'detections': rows, 'count': len(rows), 'inference_ms': 0, 'model': 'SYNTHETIC_FIXTURE'}


class Capture:
    origin = 0
    fault_period = 900
    frames = (b'occupied', b'empty')
    def __init__(self, url, settings):
        self.url, self.started, self.closed = url, time.perf_counter(), False
        self.process = SimpleNamespace(is_alive=lambda: not self.closed)
    def read(self, timeout=.2):
        time.sleep(.2)
        elapsed = time.perf_counter() - self.origin
        if self.url.endswith('/0') and elapsed > self.fault_period and elapsed % self.fault_period < 5:
            return {'error': 'SYNTHETIC_OUTAGE'}
        return {'jpeg': self.frames[int(elapsed // 20) % 2], 'monotonic_ns': time.perf_counter_ns(), 'generation': str(self.started)}
    def close(self):
        self.closed = True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--seconds', type=float, default=86400)
    parser.add_argument('--cameras', type=int, default=4, choices=range(1, 17))
    parser.add_argument('--detector', choices=['fixture', 'yolox', 'yolox-openvino'], default='fixture')
    parser.add_argument('--device', choices=['CPU', 'GPU'], default='GPU')
    parser.add_argument('--image', type=Path, help='Optional local image for real-model repeated-frame load')
    parser.add_argument('--max-rss-mb', type=float, default=3072)
    parser.add_argument('--max-disk-mb', type=float, default=4096)
    parser.add_argument('--fault-every', type=float, default=900)
    args = parser.parse_args()
    if not 10 <= args.seconds <= 172800 or args.fault_every < 10:
        parser.error('duration must be 10..172800 seconds; fault interval >=10 seconds')
    args.output.mkdir(parents=True, exist_ok=False)
    if args.detector == 'fixture':
        detector = FixtureDetector()
    else:
        import cv2
        import numpy as np
        from cctv_tracker.engine import create_detector
        detector = create_detector(args.detector, args.device)
        blank = np.zeros((240, 320, 3), np.uint8)
        image = cv2.imread(str(args.image)) if args.image else blank
        if image is None:
            raise ValueError('Input image cannot be read')
        image = cv2.resize(image, (320, 240))
        Capture.frames = tuple(cv2.imencode('.jpg', v)[1].tobytes() for v in (image, blank))
        detector.detect(Capture.frames[0])
    stop = Event()
    for name in ('SIGINT', 'SIGTERM', 'SIGBREAK'):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), lambda *_: stop.set())
    Capture.origin = time.perf_counter(); Capture.fault_period = args.fault_every
    fleet = CameraFleet(Settings(database=args.output / 'soak.sqlite3'), FairDetector(detector), capture_factory=Capture)
    fleet.startup()
    ids = []
    result = {'state': 'RUNNING', 'input': 'SIMULATED_CAPTURE', 'detector': args.detector, 'requested_seconds': args.seconds,
              'physical_cctv_validated': False, 'model': detector.manifest, 'python': platform.python_version(), 'platform': platform.platform(),
              'pid': os.getpid(), 'cameras': args.cameras, 'rss_peak_mb': 0, 'failures': []}
    started, cpu_start, previous = time.perf_counter(), time.process_time(), {}
    previous_at = started
    progress_at = {}
    try:
        for index in range(args.cameras):
            camera = fleet.add(f'SYNTHETIC camera {index}', f'rtsp://synthetic.invalid/{index}')
            ids.append(camera['id'])
            fleet.calibrate(camera['id'], {'width': 320, 'height': 240, 'camera_key': camera['camera_key'],
                'zones': [{'id': 'desk', 'name': 'Synthetic desk', 'polygon': [[0,0],[1,0],[1,1],[0,1]], 'exclusive_group': 'desk'}],
                'rules': {'occupied_confirm_seconds': .2, 'empty_confirm_seconds': .2, 'max_evidence_gap_seconds': 1}})
            fleet.configure(camera['id'], True); fleet.start_analysis(camera['id'])
        with (args.output / 'samples.jsonl').open('w') as log:
            while not stop.wait(2):
                now = time.perf_counter(); elapsed = now - started
                memory = rss_mb()
                states = fleet.snapshot()['cameras']
                cameras = []
                for state in states:
                    value = state['engine']; latest = value.get('latest')
                    if value['processed'] > previous.get(state['id'], 0):
                        progress_at[state['id']] = now
                    if now - progress_at.get(state['id'], started) > 30:
                        raise RuntimeError('No committed frame progress for 30 seconds')
                    cameras.append({'id': state['id'], 'processed': value['processed'], 'status': value['status'], 'health': value['camera_health'],
                                    'effective_fps': max(0, value['processed'] - previous.get(state['id'], 0)) / (now - previous_at),
                                    'result_age_ms': (time.perf_counter_ns() - latest['processed_monotonic_ns']) / 1e6 if latest else None,
                                    'inference_ms': latest.get('inference_ms') if latest else None})
                    previous[state['id']] = value['processed']
                previous_at = now
                disk = sum(p.stat().st_size for p in args.output.rglob('*') if p.is_file()) / 1048576
                sample = {'elapsed_seconds': elapsed, 'rss_mb': memory, 'cpu_percent_one_core': (time.process_time()-cpu_start)/elapsed*100,
                          'threads': active_count(), 'disk_mb': disk, 'cameras': cameras}
                log.write(json.dumps(sample) + '\n'); log.flush()
                result.update(elapsed_seconds=elapsed, rss_peak_mb=max(result['rss_peak_mb'], memory), latest=sample)
                atomic_write(args.output / 'result.json', json.dumps(result, indent=2).encode())
                if memory > args.max_rss_mb or disk > args.max_disk_mb:
                    raise RuntimeError('Configured resource bound exceeded')
                if any(c['status'] == 'FAILED' for c in cameras):
                    raise RuntimeError('Engine failure during soak')
                if elapsed >= args.seconds:
                    break
                if (args.output / 'STOP').exists():
                    stop.set()
        result['state'] = 'CANCELLED' if stop.is_set() else 'COMPLETED'
    except Exception as error:
        result['state'] = 'FAILED'; result['failures'].append(type(error).__name__ + ': ' + str(error))
    finally:
        try:
            fleet.shutdown()
            reports = []
            for camera in ids:
                with closing(Database(fleet.database(camera))) as db:
                    assert db.conn.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
                    assert not db.conn.execute('PRAGMA foreign_key_check').fetchall()
                    from cctv_tracker.dashboard import report
                    value = report(db)
                    for row in value['workstations']:
                        assert row['occupied_us'] + row['empty_us'] + row['unknown_us'] == row['eligible_us']
                    reports.append({'id': camera, 'workstations': value['workstations']})
            result['reports'] = reports
        except Exception as error:
            result['state'] = 'FAILED'
            result['failures'].append('Final validation: ' + type(error).__name__ + ': ' + str(error))
        result['elapsed_seconds'] = time.perf_counter() - started
        atomic_write(args.output / 'result.json', json.dumps(result, indent=2).encode())
        print(json.dumps({k: result[k] for k in ('state', 'elapsed_seconds', 'rss_peak_mb', 'failures')}), flush=True)
    raise SystemExit(0 if result['state'] == 'COMPLETED' else 1)


if __name__ == '__main__':
    main()
