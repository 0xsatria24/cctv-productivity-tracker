"""Exercise real local replay HTTP inference without writing accounting data."""
import argparse
from collections import Counter
import json
from pathlib import Path
import time
from uuid import uuid4

import av
import cv2
import httpx


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--video', type=Path, required=True)
    parser.add_argument('--url', default='http://localhost:8770')
    parser.add_argument('--frames', type=int, default=20)
    parser.add_argument('--interval',type=float,default=.5)
    parser.add_argument('--start-seconds',type=float,default=0)
    parser.add_argument('--output', type=Path, default=Path('runtime/reid-demo/verification.json'))
    args = parser.parse_args()
    rows, statuses, rejected = [], Counter(), Counter()
    replay_id = str(uuid4())
    started = time.perf_counter()
    with httpx.Client(base_url=args.url, timeout=60) as client, av.open(str(args.video)) as container:
        client.get('/').raise_for_status()
        origin, next_sample = None, 0.
        for frame in container.decode(video=0):
            if frame.time is None:
                raise ValueError('Missing media timestamp')
            if origin is None:
                origin = frame.time
            elapsed = frame.time-origin
            if elapsed < args.start_seconds:
                continue
            if elapsed+1e-8 < next_sample:
                continue
            next_sample = elapsed+args.interval
            image = frame.to_ndarray(format='bgr24')
            height, width = image.shape[:2]
            scale = min(1, 960/max(height, width), (1280*720/(height*width))**.5)
            image = cv2.resize(image, (round(width*scale), round(height*scale)))
            ok, jpeg = cv2.imencode('.jpg', image, [cv2.IMWRITE_JPEG_QUALITY, 90])
            if not ok:
                raise ValueError('JPEG encoding failed')
            seq = len(rows)+1
            response = client.post('/pilot/v1/replay/frame', content=jpeg.tobytes(), headers={
                'Content-Type': 'image/jpeg', 'Origin': args.url, 'X-Replay-Id': replay_id,
                'X-Replay-Generation': '0', 'X-Replay-Sequence': str(seq), 'X-Replay-Time': str(elapsed)})
            response.raise_for_status()
            packet = response.json()
            assert packet['recorded'] is False and packet['duration_accounting'] is False
            report = packet['reid']
            statuses[report['status']] += 1
            rejected.update(row['reason'] for row in report['rejections'])
            rows.append({'frame': seq, 'media_seconds': elapsed, 'people': packet['count'],
                         'inference_ms': packet['inference_ms'], 'reid': report})
            print(json.dumps({'frame': seq, 'people': packet['count'], 'reid': report['status'],
                              'gallery_sessions': report['gallery_sessions']}), flush=True)
            if seq >= args.frames:
                break
    summary = {'source': str(args.video), 'frames': len(rows), 'statuses': dict(statuses),
               'quality_rejections': dict(rejected), 'max_people': max((r['people'] for r in rows), default=0),
               'max_gallery_sessions': max((r['reid']['gallery_sessions'] for r in rows), default=0),
               'applied_recoveries':sum(d['action']=='MATCH' for r in rows for d in r['reid']['decisions']),
               'wall_seconds': round(time.perf_counter()-started, 2),
               'validation': 'Real-model execution only; no labeled identity accuracy evaluation.', 'rows': rows}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in summary.items() if k != 'rows'}, indent=2))


if __name__ == '__main__':
    main()
