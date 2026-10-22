"""Import user factory clips and run full decoding with sampled real inference."""
from pathlib import Path
from dataclasses import replace
from datetime import datetime, timezone
import json
import shutil
import time
import av
import cv2
from cctv_tracker.config import load_settings
from cctv_tracker.persistence import Database
from cctv_tracker.pipeline import Pipeline
from cctv_tracker.vision import Detection
from cctv_tracker.openvino_yolox import OpenVinoYoloX

root = Path(__file__).resolve().parents[1]
out = root / 'runtime' / 'factory-video-test' / datetime.now().strftime('%Y%m%d-%H%M%S')
out.mkdir(parents=True)
detector = OpenVinoYoloX(device='CPU', cache_dir=out / 'openvino-cache')
results = []
for name in ('075831', '084248', '091346', '090455'):
    source = Path('C:/Users/muham/Videos/videos/20180903') / (name + '.mp4')
    video = out / source.name
    shutil.copy2(source, video)
    settings = replace(load_settings(root / 'config/pilot.example.json'), inference_fps=2,
                       database=out / (name + '.sqlite3'))
    db = Database(settings.database)
    start = int(datetime.now(timezone.utc).timestamp() * 1e6)
    pipeline = Pipeline(settings, db, start, 'LOCAL_VIDEO_REPLAY', detector.sha, detector.manifest)
    row = dict(file=name + '.mp4', decoded_frames=0, sampled_frames=0, frames_with_people=0,
               max_people=0, tracks=[], test_zones='Example zones only; not calibrated workstations')
    tracks = set()
    begun = time.perf_counter()
    next_sample = 0
    origin = None
    with av.open(str(video)) as container:
        stream = container.streams.video[0]
        row.update(width=stream.width, height=stream.height, fps=float(stream.average_rate))
        for frame in container.decode(video=0):
            row['decoded_frames'] += 1
            if origin is None:
                origin = frame.time
            elapsed = frame.time - origin
            row['duration_seconds'] = elapsed
            if elapsed + 1e-8 < next_sample:
                continue
            next_sample = elapsed + 0.5
            image = frame.to_ndarray(format='bgr24')
            ok, jpeg = cv2.imencode('.jpg', image)
            if not ok:
                raise RuntimeError('JPEG encoding failed')
            detected = detector.detect(jpeg.tobytes())
            detections = [Detection(tuple(d['box']), d['confidence']) for d in detected['detections']]
            row['sampled_frames'] += 1
            row['frames_with_people'] += bool(detections)
            row['max_people'] = max(row['max_people'], len(detections))
            state = pipeline.feed(detections, start + round(elapsed * 1e6), round(elapsed * 1e9), row['sampled_frames'], name)
            tracks.update(pipeline.tracker.last_tracks)
            if row['sampled_frames'] == 1 or row['sampled_frames'] % 120 == 0:
                for d in detections:
                    x1,y1,x2,y2 = d.box
                    cv2.rectangle(image, (int(x1*stream.width),int(y1*stream.height)), (int(x2*stream.width),int(y2*stream.height)), (0,220,0), 2)
                cv2.imwrite(str(out / f'{name}-{row["sampled_frames"]}.jpg'), image)
                print(f'{name}: {elapsed:.1f}s, people={len(detections)}', flush=True)
    row['report'] = pipeline.finish()
    row['tracks'] = sorted(tracks)
    row['wall_seconds'] = round(time.perf_counter() - begun, 2)
    row['sqlite_integrity'] = db.conn.execute('PRAGMA integrity_check').fetchone()[0]
    db.close()
    results.append(row)
    (out / 'results.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
    print(json.dumps({k:v for k,v in row.items() if k not in ('report','tracks')}), flush=True)
print(f'RESULTS: {out}', flush=True)
