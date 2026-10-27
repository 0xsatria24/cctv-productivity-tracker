"""Local video/runtime measurements, without identity ground-truth claims."""
import argparse
from collections import Counter
import ctypes
from ctypes import wintypes
from dataclasses import replace
import hashlib
import importlib.metadata
import json
import math
from pathlib import Path
import platform
import statistics
import sys
import time
from uuid import uuid4


class ProcessMemory(ctypes.Structure):
    _fields_ = [('cb', wintypes.DWORD), ('faults', wintypes.DWORD)] + [
        (name, ctypes.c_size_t) for name in (
            'peak_rss', 'rss', 'peak_paged', 'paged', 'peak_nonpaged', 'nonpaged', 'private', 'peak_private')]


def rss_bytes():
    if sys.platform != 'win32':
        return None
    kernel = ctypes.WinDLL('kernel32')
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    psapi = ctypes.WinDLL('psapi')
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessMemory), wintypes.DWORD]
    info = ProcessMemory()
    info.cb = ctypes.sizeof(info)
    if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(info), info.cb):
        raise ctypes.WinError()
    return info.rss


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--video', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--seconds', type=float, default=265)
    parser.add_argument('--source-root', type=Path)
    parser.add_argument('--detail', action='store_true')
    parser.add_argument('--background-reid', action='store_true')
    parser.add_argument('--paced', action='store_true', help='Replay at media speed to exercise background ReID')
    parser.add_argument('--reid-mode', choices=['off', 'shadow', 'active'], default='off')
    args = parser.parse_args()
    if not 0 < args.seconds <= 1800:
        parser.error('--seconds must be in (0,1800]')
    if args.source_root:
        sys.path.insert(0, str(args.source_root.resolve()))
    import av
    import cv2
    import cctv_tracker.sessions as sessions_module
    from cctv_tracker.config import Settings
    from cctv_tracker.openvino_yolox import OpenVinoYoloX
    from cctv_tracker.reid.config import ReIdRules
    from cctv_tracker.replay_tracking import ReplayFrame, ReplayTracking
    from cctv_tracker.person_detection import DetectionTuning

    root = Path(__file__).resolve().parents[1]
    rules = ReIdRules(mode=args.reid_mode, manifest_path=str(
        root/'models/reid/person-reidentification-retail-0287/manifest.json'))
    tuning = DetectionTuning(detail=args.detail)
    detector = OpenVinoYoloX(model_path=root/'models/webcam-yolox.onnx', device='GPU', tuning=tuning)
    replay = ReplayTracking(replace(Settings(), reid=rules, detection=tuning), background_reid=args.background_reid)
    rid, rows, statuses, seen = str(uuid4()), [], Counter(), set()
    memory = []
    started = time.perf_counter()
    with av.open(str(args.video)) as container:
        stream = container.streams.video[0]
        metadata = {'width': stream.width, 'height': stream.height, 'fps': str(stream.average_rate),
                    'duration_seconds': float(stream.duration*stream.time_base) if stream.duration else None}
        origin, next_sample = None, 0
        for frame in container.decode(video=0):
            if frame.time is None:
                raise ValueError('Source timestamps missing')
            origin = frame.time if origin is None else origin
            at = frame.time-origin
            if at > args.seconds:
                break
            if at+1e-8 < next_sample:
                continue
            next_sample = at+.2
            if args.paced:
                time.sleep(max(0, started+at-time.perf_counter()))
            image = frame.to_ndarray(format='bgr24')
            height, width = image.shape[:2]
            scale = min(1, 960/max(height, width), (1280*720/(height*width))**.5)
            if scale < 1:
                image = cv2.resize(image, (round(width*scale), round(height*scale)))
            ok, encoded = cv2.imencode('.jpg', image, [cv2.IMWRITE_JPEG_QUALITY, 90])
            if not ok:
                raise ValueError('JPEG encoding failed')
            tick = time.perf_counter()
            packet = replay.process(detector, encoded.tobytes(), ReplayFrame(rid, 0, len(rows)+1, at))
            elapsed = (time.perf_counter()-tick)*1000
            assert not packet['recorded'] and not packet['duration_accounting']
            assert all(r.get('prediction_age_seconds', 0) <= .4 for r in packet['display_detections'])
            statuses[packet['reid']['status']] += 1
            seen.update(r['session_id'] for r in packet['detections'] if r['session_id'])
            rows.append({'media_seconds': at, 'wall_ms': elapsed, 'count': packet['count'],
                         'detections': packet['detections'], 'display_count': len(packet['display_detections']),
                         'reid_status': packet['reid']['status'],
                         'reid_ms': packet['reid'].get('elapsed_ms'),
                         'gallery_sessions': packet['reid']['gallery_sessions']})
            if len(rows) % 100 == 0 or len(rows) == 1:
                memory.append({'frame': len(rows), 'rss_bytes': rss_bytes()})
                print(json.dumps({'frame': len(rows), 'media_seconds': round(at, 2),
                                  'rss_mib': round(memory[-1]['rss_bytes']/2**20, 2),
                                  'reid': packet['reid']['status']}), flush=True)
    if len(rows) < 2:
        raise ValueError('Need at least two sampled frames')
    memory.append({'frame': len(rows), 'rss_bytes': rss_bytes()})
    warm = sorted(row['wall_ms'] for row in rows[1:])
    manager = replay.streams[rid].sessions
    report = {'source': str(args.video.resolve()), 'source_sha256': hashlib.sha256(args.video.read_bytes()).hexdigest(),
              'metadata': metadata, 'environment': {'platform': platform.platform(), 'python': platform.python_version(),
              'sessions_module': sessions_module.__file__, 'packages': {name: importlib.metadata.version(name)
                  for name in ('numpy', 'av', 'supervision', 'openvino', 'opencv-python')}},
              'detector': detector.manifest, 'reid_mode': args.reid_mode,
              'background_reid': args.background_reid, 'paced': args.paced, 'frames': len(rows),
              'warm_median_ms': statistics.median(warm), 'warm_p95_ms': warm[math.ceil(len(warm)*.95)-1],
              'warm_throughput_fps': 1000/statistics.mean(warm), 'cold_first_frame_ms': rows[0]['wall_ms'],
              'wall_seconds': time.perf_counter()-started, 'rss_samples': memory,
              'empty_frames': sum(row['count'] == 0 for row in rows), 'sessions_created': len(seen),
              'reid_statuses': dict(statuses), 'session_metrics': dict(manager.metrics),
              'retained_sessions': len(manager.sessions),
              'gallery_sessions': len(replay.streams[rid].reid.gallery.entries),
              'validation': 'Unlabeled video execution; no IDF1/HOTA, identity accuracy or multi-camera capacity claim.',
              'vram': 'Unavailable; Iris Xe uses shared memory. RSS excludes GPU allocations.', 'rows': rows}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items() if k not in {'rows', 'environment', 'detector'}}, indent=2))


if __name__ == '__main__':
    main()
