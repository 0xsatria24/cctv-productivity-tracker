"""Compare measured replay detection/session continuity on identical frames."""
import argparse
from dataclasses import replace
import json
from pathlib import Path
import statistics
import time
from uuid import uuid4

import av
import cv2
from cctv_tracker.config import Settings, SessionRules
from cctv_tracker.reid.config import ReIdRules
from cctv_tracker.openvino_yolox import OpenVinoYoloX
from cctv_tracker.nanodet import NanoDetDetector
from cctv_tracker.person_detection import DetectionTuning
from cctv_tracker.replay_tracking import ReplayFrame, ReplayTracking


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--video', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--seconds', type=float, default=20)
    parser.add_argument('--confidence', type=float, default=.45)
    parser.add_argument('--tracking-confidence', type=float, default=.1)
    parser.add_argument('--calibration', type=Path, help='Replay calibration JSON: zones and association, independently drawn')
    parser.add_argument('--device', choices=['CPU','GPU'], default='GPU')
    parser.add_argument('--profiles', nargs='+', choices=['balanced','detail','nanodet'], default=['balanced','detail'])
    parser.add_argument('--reid-mode',choices=['off','shadow','active'],default='off')
    parser.add_argument('--reid-policy',choices=['motion','short_occlusion'],default='short_occlusion')
    args = parser.parse_args()
    if not 0 < args.seconds <= 1800:
        parser.error('--seconds must be in (0,1800]')
    if 'nanodet' in args.profiles and args.confidence != .45:
        parser.error('NanoDet comparison requires the shared fixed confidence .45')
    args.output.parent.mkdir(parents=True,exist_ok=True)
    frame_dir=args.output.parent/(args.output.stem+'-frames')
    frame_dir.mkdir(exist_ok=False)
    frames, next_sample = [], 0.
    with av.open(str(args.video)) as container:
        origin = None
        for frame in container.decode(video=0):
            origin = frame.time if origin is None else origin
            elapsed = frame.time-origin
            if elapsed > args.seconds:
                break
            if elapsed+1e-8 < next_sample:
                continue
            next_sample = elapsed+.2
            image = frame.to_ndarray(format='bgr24')
            h,w = image.shape[:2]
            scale = min(1, 960/max(h,w), (1280*720/(h*w))**.5)
            image = cv2.resize(image, (round(w*scale), round(h*scale)))
            path=frame_dir/f'{len(frames)+1:06d}.jpg'
            path.write_bytes(cv2.imencode('.jpg', image, [cv2.IMWRITE_JPEG_QUALITY, 90])[1].tobytes())
            frames.append((elapsed,path))
    if len(frames)<2:
        parser.error('Video must contain at least two sampled frames')
    results = {}
    for name in args.profiles:
        tuning = DetectionTuning(confidence=args.confidence, tracking_confidence=args.tracking_confidence, detail=name=='detail')
        detector = NanoDetDetector() if name=='nanodet' else OpenVinoYoloX(device=args.device, tuning=tuning)
        manifest = Path(__file__).resolve().parents[1]/'models/reid/person-reidentification-retail-0287/manifest.json'
        rules = ReIdRules(mode=args.reid_mode, manifest_path=str(manifest), recovery_policy=args.reid_policy,
                         min_confidence=.55,sample_interval_seconds=.2,confirm_seconds=.4,max_gap_seconds=2,max_extra_latency_ms=5000)
        replay = ReplayTracking(replace(Settings(), detection=tuning,reid=rules,
                                sessions=SessionRules(recovery_confirmation_window_seconds=2)))
        replay_id = str(uuid4())
        revision=0
        if args.calibration:
            calibration=json.loads(args.calibration.read_text(encoding='utf-8'))
            revision=replay.configure(replay_id,{**calibration,'expected_revision':0})['calibration_revision']
        rows, seen, times = [],set(),[]
        for seq,(elapsed,path) in enumerate(frames,1):
            began = time.perf_counter()
            packet = replay.process(detector,path.read_bytes(),ReplayFrame(replay_id,0,seq,elapsed,revision))
            times.append((time.perf_counter()-began)*1000)
            seen.update(d['session_id'] for d in packet['detections'] if d['session_id'])
            rows.append({'time':elapsed,'image':str(path),'count':packet['count'],'detections':packet['detections'],
                         'workstations':packet['workstations'],'reid':packet['reid'],'tracking':packet['tracking']})
        manager = replay.streams[replay_id].sessions
        results[name] = {'frames':len(rows),'video':str(args.video),'device':'CPU' if name=='nanodet' else args.device,'detector':dict(detector.manifest),
                         'confidence':args.confidence,'tracking_confidence':args.tracking_confidence,
                         'reid_mode':args.reid_mode,'calibration_revision':revision,
                         'empty_frames':sum(not r['count'] for r in rows),
                         'sessions_created':len(seen),'session_metrics':dict(manager.metrics),
                         'unmerged_session_starts':manager.metrics['started']-manager.metrics['recovered'],
                         'warm_median_ms':round(statistics.median(times[1:]),2),'rows':rows}
        results[name]['workstation_totals']=rows[-1]['workstations']
        results[name]['tracking_candidates']=sum(r['tracking']['tracking_candidates'] for r in rows)
        results[name]['matched_tracking_candidates']=sum(r['tracking']['matched_tracking_candidates'] for r in rows)
        print(name, json.dumps({k:v for k,v in results[name].items() if k!='rows'}),flush=True)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(results,indent=2),encoding='utf-8')


if __name__ == '__main__':
    main()
