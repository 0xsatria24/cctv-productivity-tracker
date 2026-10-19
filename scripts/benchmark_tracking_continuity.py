"""Compare candidate filtering on local video. Continuity metrics, not accuracy."""
import argparse
import json
from pathlib import Path
import time

import cv2
import numpy as np

from cctv_tracker.openvino_yolox import OpenVinoYoloX
from cctv_tracker.vision import Detection, Tracker


def summary(rows):
    return {'samples': len(rows), 'empty_samples': sum(not row for row in rows),
            'unique_track_ids': len({d.track_id for row in rows for d in row if d.track_id}),
            'empty_transitions': sum(bool(a) != bool(b) for a, b in zip(rows, rows[1:]))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--device', default='GPU', choices=['CPU', 'GPU'])
    parser.add_argument('--fps', type=int, default=5)
    parser.add_argument('videos', nargs='+', type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    detector = OpenVinoYoloX(args.model, device=args.device, cache_dir=args.output / 'cache')
    detector.detect(cv2.imencode('.jpg', np.zeros((360, 640, 3), np.uint8))[1].tobytes())
    results = []
    for path in args.videos:
        capture = cv2.VideoCapture(str(path))
        fps = capture.get(cv2.CAP_PROP_FPS)
        if not capture.isOpened() or fps <= 0:
            raise ValueError(f'Cannot read {path.name}')
        old, new = Tracker(args.fps, 3), Tracker(args.fps, 3)
        old.tracker.max_time_lost = int(args.fps / 30 * 30)
        old.tracker.det_thresh = 0.35
        before, after, timings, samples = [], [], [], []
        index, next_time = 0, 0.0
        try:
            while True:
                ok, image = capture.read()
                if not ok:
                    break
                at = index / fps
                index += 1
                if at + 0.001 < next_time:
                    continue
                next_time += 1 / args.fps
                image = cv2.resize(image, (640, 360))
                jpeg = cv2.imencode('.jpg', image, [cv2.IMWRITE_JPEG_QUALITY, 75])[1].tobytes()
                start = time.perf_counter()
                result = detector.detect(jpeg)
                timings.append((time.perf_counter() - start) * 1000)
                high = [Detection(tuple(d['box']), d['confidence']) for d in result['detections']]
                candidates = [Detection(tuple(d['box']), d['confidence']) for d in result['tracking_candidates']]
                a, b = old.update(high, at, 'video'), new.update(candidates, at, 'video')
                b = [d for d in b if d.track_id is not None or d.confidence >= .45]
                before.append(a); after.append(b)
                samples.append({'seconds': round(at, 3), 'before': [dict(box=d.box, confidence=d.confidence, id=d.track_id) for d in a],
                                'after': [dict(box=d.box, confidence=d.confidence, id=d.track_id) for d in b],
                                'candidates': result['tracking_candidates']})
                if len(samples) % 50 == 0:
                    print(f'{path.name}: {len(samples)} samples ({at:.1f}s)', flush=True)
        finally:
            capture.release()
        row = {'file': path.name, 'sample_fps': args.fps, 'before': summary(before), 'after': summary(after),
               'inference_ms_p50': round(float(np.median(timings)), 1), 'inference_ms_p95': round(float(np.percentile(timings, 95)), 1),
               'limitation': 'Unlabelled continuity comparison; no precision/recall or worker productivity claim.'}
        (args.output / (path.stem + '.json')).write_text(json.dumps({'summary': row, 'samples': samples}, indent=2))
        results.append(row)
        print(json.dumps(row), flush=True)
    (args.output / 'summary.json').write_text(json.dumps(results, indent=2))


if __name__ == '__main__':
    main()
