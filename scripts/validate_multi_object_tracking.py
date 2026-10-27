"""Reproduce irregular-cadence MOT regression; optional real-video smoke replay."""
import argparse
from contextlib import closing
import json
import os
from pathlib import Path
import subprocess
import sys
import types

from cctv_tracker.config import Settings, Zone
from cctv_tracker.persistence import Database
from cctv_tracker.pipeline import Pipeline
from cctv_tracker.vision import Detection, Tracker

ROOT = Path(__file__).resolve().parents[1]


def irregular(factory):
    tracker = factory(5, 1)
    seen, owners, observations = {}, {}, []
    false_merges = 0
    matched = 0
    for at in (0, .2, .4, .6, .8, 1.6, 1.8, 2):
        labeled = [('A', Detection((.05 + .08 * at, .1, .13 + .08 * at, .3), .95)),
                   ('B', Detection((.55 + .08 * at, .6, .63 + .08 * at, .8), .95))]
        rows = tracker.update([d for _, d in labeled], at, 'irregular')
        for (label, _), row in zip(labeled, rows):
            sid = row.track_id
            if sid is not None:
                matched += 1
                false_merges += sid in owners and owners[sid] != label
                owners[sid] = label
                seen.setdefault(label, set()).add(sid)
        observations.append({'seconds': at, 'track_ids': [d.track_id for d in rows]})
    return {'measured_detections': 16, 'matched_detections': matched, 'false_track_merges': false_merges,
            'tracks_per_person': {k: len(v) for k, v in seen.items()}, 'observations': observations}


def video_smoke(path, output, max_frames):
    import av
    import cv2
    from cctv_tracker.engine import create_detector
    settings = Settings(database=output / 'video.sqlite3', zones=(Zone('evaluation', 'Uncalibrated evaluation area', ((0,0),(1,0),(1,1),(0,1))),))
    detector = create_detector('yolox-openvino', 'CPU')
    detector.cache_dir = output / 'openvino-cache'
    origin, next_sample, seq = None, 0, 0
    frames, ids = [], set()
    with closing(Database(settings.database)) as db:
        pipeline = Pipeline(settings, db, 1_000_000, 'LOCAL_VIDEO_REPLAY', detector.sha, detector.manifest)
        try:
            with av.open(str(path)) as container:
                for frame in container.decode(video=0):
                    if frame.time is None:
                        raise ValueError('Media PTS required')
                    origin = frame.time if origin is None else origin
                    elapsed = frame.time - origin
                    if elapsed + 1e-8 < next_sample:
                        continue
                    next_sample = elapsed + .5
                    image = frame.to_ndarray(format='bgr24')
                    detected = detector.detect(cv2.imencode('.jpg', image)[1].tobytes())
                    rows = [Detection(tuple(d['box']), d['confidence']) for d in detected['detections']]
                    seq += 1
                    result = pipeline.feed(rows, 1_000_000 + round(elapsed * 1e6), round(elapsed * 1e9), seq, 'local-video')
                    ids.update(d['session_id'] for d in result['detections'] if d['session_id'])
                    frames.append({'seconds': elapsed, 'tracking': result['tracking'], 'detections': result['detections']})
                    height, width = image.shape[:2]
                    for d in result['detections']:
                        x1,y1,x2,y2 = d['box']; left,top = int(x1*width),int(y1*height)
                        cv2.rectangle(image, (left,top), (int(x2*width),int(y2*height)), (0,190,100), 2)
                        label = (d['session_id'] or 'UNASSIGNED')[:8]
                        cv2.putText(image, label, (left,max(14,top)), cv2.FONT_HERSHEY_SIMPLEX,.45,(0,190,100),1)
                    if seq in (1, max_frames) or seq % 10 == 0:
                        cv2.imwrite(str(output / f'video-{seq:03d}.jpg'), image)
                    if seq >= max_frames:
                        break
        except BaseException:
            pipeline.finish('INTERRUPTED')
            raise
        else:
            pipeline.finish()
        integrity = db.conn.execute('PRAGMA integrity_check').fetchone()[0]
    return {'source': str(path), 'sampled_frames': seq, 'sample_interval_seconds': .5,
            'distinct_sessions': len(ids), 'integrity': integrity, 'frames': frames,
            'notice': 'Real-video smoke replay with uncalibrated evaluation zone; no annotated identity ground truth or accuracy score.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True, help='New output directory')
    parser.add_argument('--video', type=Path)
    parser.add_argument('--max-video-frames', type=int, default=40)
    args = parser.parse_args()
    if not 1 <= args.max_video_frames <= 1000:
        parser.error('max-video-frames must be between 1 and 1000')
    if args.video and not args.video.is_file():
        parser.error('Local video not found')
    args.output.mkdir(parents=True, exist_ok=False)
    os.environ.setdefault('MPLCONFIGDIR', str(ROOT / 'runtime/matplotlib'))
    os.environ.setdefault('MPLBACKEND', 'Agg')
    source = subprocess.run(['git', 'show', 'HEAD:src/cctv_tracker/vision.py'], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    baseline = types.ModuleType('cctv_tracker._mot_baseline')
    baseline.__package__ = 'cctv_tracker'
    sys.modules[baseline.__name__] = baseline
    exec(compile(source, '<HEAD vision baseline>', 'exec'), baseline.__dict__)
    report = {'notice': 'Synthetic trajectory fixture uses real ByteTrack; it is not factory identity accuracy.',
              'baseline_revision': subprocess.run(['git','rev-parse','HEAD'], cwd=ROOT, capture_output=True,text=True,check=True).stdout.strip(),
              'irregular_baseline': irregular(baseline.Tracker), 'irregular_current': irregular(Tracker)}
    if args.video:
        report['video_smoke'] = video_smoke(args.video, args.output, args.max_video_frames)
    (args.output / 'results.json').write_text(json.dumps(report,indent=2), encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k != 'video_smoke'},indent=2))
    if args.video:
        print(json.dumps({k:v for k,v in report['video_smoke'].items() if k!='frames'},indent=2))


if __name__ == '__main__':
    main()
