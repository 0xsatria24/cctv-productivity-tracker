"""Compare the same YOLOX model across runtimes; no physical camera is opened."""
import argparse
import json
from pathlib import Path
import statistics
import time
import cv2
import numpy as np
from cctv_tracker.webcam import WebcamDetector
from cctv_tracker.openvino_yolox import OpenVinoYoloX


def iou(a, b):
    area = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - area
    return area / union if union else 0


def compare(reference, actual):
    remaining = list(actual['detections'])
    overlaps, deltas = [], []
    for detection in reference['detections']:
        if not remaining:
            return {'count_match': False}
        match = max(remaining, key=lambda d: iou(detection['box'], d['box']))
        overlaps.append(iou(detection['box'], match['box']))
        deltas.append(abs(detection['confidence'] - match['confidence']))
        remaining.remove(match)
    return {'count_match': reference['count'] == actual['count'], 'min_box_iou': min(overlaps, default=1), 'max_confidence_delta': max(deltas, default=0)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--image', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=Path('runtime/openvino-benchmark.json'))
    parser.add_argument('--samples', type=int, default=10)
    parser.add_argument('--backend', choices=['all', 'onnx', 'cpu', 'gpu'], default='all')
    args = parser.parse_args()
    if not 3 <= args.samples <= 100:
        parser.error('samples must be 3 to 100')
    image = cv2.imread(str(args.image))
    if image is None:
        parser.error('image not found')
    images = {'person': image, 'blank': np.zeros((360, 640, 3), np.uint8),
              'portrait': cv2.copyMakeBorder(image, 240, 240, 0, 0, cv2.BORDER_CONSTANT),
              'dimmed': (image * 0.5).astype(np.uint8), 'blurred': cv2.GaussianBlur(image, (7, 7), 1.5),
              'downsampled': cv2.resize(image, (320, 240), interpolation=cv2.INTER_AREA)}
    frames = {name: cv2.imencode('.jpg', img)[1].tobytes() for name, img in images.items()}
    factories = {'onnx_cpu_2threads': WebcamDetector,
                 'openvino_cpu_2threads': lambda: OpenVinoYoloX(threads=2),
                 'openvino_cpu_4threads': lambda: OpenVinoYoloX(threads=4),
                 'openvino_gpu_fp32': lambda: OpenVinoYoloX(device='GPU')}
    if args.backend != 'all':
        factories = {key: value for key, value in factories.items() if key.startswith({'onnx': 'onnx', 'cpu': 'openvino_cpu', 'gpu': 'openvino_gpu'}[args.backend])}
    results, references = {}, {}
    if args.backend != 'all':
        reference = WebcamDetector()
        references = {key: reference.detect(jpeg) for key, jpeg in frames.items()}
        del reference
    for name, factory in factories.items():
        started = time.perf_counter()
        detector = factory()
        detector.detect(frames['person'])
        cold = time.perf_counter() - started
        for _ in range(3):
            detector.detect(frames['person'])
        values = [detector.detect(frames['person'])['inference_ms'] for _ in range(args.samples)]
        detections = {key: detector.detect(jpeg) for key, jpeg in frames.items()}
        if not references:
            references = detections
        equivalence = {key: compare(references[key], data) for key, data in detections.items()}
        result = {'model': detector.runtime_label, 'model_sha256': detector.sha, 'manifest': detector.manifest,
                  'first_load_seconds': round(cold, 3), 'samples_ms': values, 'median_ms': statistics.median(values),
                  'p95_ms': float(np.percentile(values, 95)), 'equivalence': equivalence}
        results[name] = result
        print(json.dumps({name: result}, indent=2), flush=True)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps({'image': str(args.image), 'results': results, 'note': 'Runtime equivalence smoke test, not camera accuracy validation'}, indent=2), encoding='utf-8')
        del detector
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({'image': str(args.image), 'results': results, 'note': 'Runtime equivalence smoke test, not camera accuracy validation'}, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
