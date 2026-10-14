"""Measured warmed detector latency; no physical camera or recording."""
import json
import statistics
import cv2
import numpy as np
from cctv_tracker.webcam import WebcamDetector
from cctv_tracker.nanodet import NanoDetDetector


def main():
    frame = cv2.imencode('.jpg', np.zeros((360, 640, 3), np.uint8))[1].tobytes()
    results = {}
    for name, factory in [('yolox', WebcamDetector), ('nanodet', NanoDetDetector)]:
        detector = factory()
        detector.detect(frame)
        latencies = [detector.detect(frame)['inference_ms'] for _ in range(10)]
        results[name] = {'source': 'blank synthetic JPEG', 'provider': 'CPU', 'samples_ms': latencies,
                         'median_ms': statistics.median(latencies), 'max_ms': max(latencies)}
    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    main()
