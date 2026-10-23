"""Compare balanced/detail detections on the same local images, without tracking."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import statistics

import cv2
import numpy as np

from cctv_tracker.engine import create_detector
from cctv_tracker.person_detection import DetectionTuning


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('images', type=Path, help='Directory of original JPEG/PNG samples, without drawn boxes')
    parser.add_argument('--output', type=Path, required=True, help='New directory for results and annotated comparisons')
    parser.add_argument('--device', choices=['CPU', 'GPU'], default='CPU')
    parser.add_argument('--confidence', type=float, default=.45)
    args = parser.parse_args()
    paths = sorted(p for p in args.images.iterdir() if p.suffix.lower() in {'.jpg', '.jpeg', '.png'} and p.is_file())
    if not paths:
        parser.error('No images found')
    args.output.mkdir(parents=True, exist_ok=False)
    report = {'basis': 'same_image_profile_comparison', 'accuracy_measured': False,
              'note': 'Counts are not recall or precision. Review boxes against independent labels before choosing a profile.', 'images': [], 'profiles': {}}
    for profile in ('balanced', 'detail'):
        tuning = DetectionTuning(confidence=args.confidence, detail=profile == 'detail')
        detector = create_detector('yolox-openvino', args.device, tuning=tuning)
        detector.cache_dir = args.output / 'openvino-cache'
        detector.detect(cv2.imencode('.jpg', np.zeros((64, 64, 3), np.uint8))[1].tobytes())
        times = []
        for index, path in enumerate(paths):
            result = detector.detect(path.read_bytes())
            if profile == 'balanced':
                report['images'].append({'image': path.name})
            report['images'][index][profile] = result
            times.append(result['inference_ms'])
            image = cv2.imread(str(path)); height, width = image.shape[:2]
            for detection in result['detections']:
                x1, y1, x2, y2 = detection['box']
                a, b = int(x1 * width), int(y1 * height)
                cv2.rectangle(image, (a, b), (int(x2 * width), int(y2 * height)), (0, 200, 100), 2)
                cv2.putText(image, f"{detection['confidence']:.2f}", (a, max(15, b)), cv2.FONT_HERSHEY_SIMPLEX, .5, (0, 200, 100), 1)
            cv2.imwrite(str(args.output / f'{index:03d}-{profile}.jpg'), image)
            print(f'{profile}: {path.name} people={result["count"]} ms={result["inference_ms"]}', flush=True)
        report['profiles'][profile] = {'tuning': asdict(tuning), 'runtime': detector.manifest,
                                       'median_ms': statistics.median(times), 'p95_ms': float(np.percentile(times, 95))}
    (args.output / 'results.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(f'Results: {args.output / "results.json"}', flush=True)


if __name__ == '__main__':
    main()
