"""Finite shared-model smoke test. File frames simulate sources, not live cameras."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import statistics
import time

from cctv_tracker.engine import create_detector
from cctv_tracker.inference import InferenceScheduler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--images', nargs='+', type=Path, required=True)
    parser.add_argument('--streams', type=int, default=4)
    parser.add_argument('--samples', type=int, default=6)
    parser.add_argument('--detector', choices=('yolox', 'yolox-openvino'), default='yolox')
    parser.add_argument('--device', choices=('CPU', 'GPU'), default='CPU')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.streams <= 64 or not 1 <= args.samples <= 100:
        parser.error('Use 1..64 streams and 1..100 samples per stream')
    frames = [path.read_bytes() for path in args.images]
    raw = create_detector(args.detector, args.device)
    scheduler = InferenceScheduler(raw)
    warmup_started = time.perf_counter()
    scheduler.bind('warmup').detect(frames[0])
    warmup_ms = (time.perf_counter() - warmup_started)*1000
    started = time.perf_counter()

    def run(index):
        source = f'file-source-{index}'
        lane = scheduler.bind(source, max_fps=5)
        rows = []
        for sequence in range(1, args.samples + 1):
            item = {'jpeg': frames[index % len(frames)], 'monotonic_ns': time.perf_counter_ns(), 'generation': source}
            try:
                result, selected = lane.detect_latest(item, None, 3)
                assert selected is item and result['scheduler']['source_id'] == source
                rows.append({'sequence': sequence, 'count': result['count'], **result['scheduler']})
            except Exception as error:
                rows.append({'sequence': sequence, 'error': type(error).__name__})
        return {'source': source, 'samples': rows}

    try:
        with ThreadPoolExecutor(max_workers=args.streams) as pool:
            sources = list(pool.map(run, range(args.streams)))
        elapsed = time.perf_counter() - started
        rows = [row for source in sources for row in source['samples']]
        successful = [row for row in rows if 'error' not in row]
        report = {'kind': 'file-source-scheduler-smoke', 'live_cameras': False, 'duration_accounting': False,
                  'detector': raw.runtime_label, 'model_sha256': raw.sha, 'runtime': raw.manifest,
                  'inputs': [str(p) for p in args.images], 'sources': sources,
                  'warmup_ms': round(warmup_ms, 2), 'elapsed_seconds': round(elapsed, 3),
                  'completed': len(successful), 'failed': len(rows) - len(successful),
                  'aggregate_fps': round(len(successful) / elapsed, 2),
                  'median_queue_ms': statistics.median(row['queue_ms'] for row in successful) if successful else None,
                  'max_queue_ms': max((row['queue_ms'] for row in successful), default=None),
                  'median_service_ms': statistics.median(row['service_ms'] for row in successful) if successful else None,
                  'scheduler': scheduler.snapshot()}
    finally:
        scheduler.close()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({key: report[key] for key in ('detector', 'completed', 'failed', 'aggregate_fps', 'median_queue_ms', 'median_service_ms')}))
    print(f'Report: {args.output}')
    return int(bool(report['failed']))


if __name__ == '__main__':
    raise SystemExit(main())
