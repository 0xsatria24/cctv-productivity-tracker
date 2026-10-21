"""Reproducible unlabelled box-continuity check on fixed local video frames."""
import argparse
import json
from pathlib import Path
import time

import cv2
import numpy as np

from cctv_tracker.vision import Detection, Tracker
from cctv_tracker.display_tracks import DisplayTracks


def metrics(rows):
    return {'samples':len(rows),'empty_samples':sum(not r for r in rows),
            'visibility_transitions':sum(bool(a)!=bool(b) for a,b in zip(rows,rows[1:])),
            'anonymous_ids':len({d['track_id'] for r in rows for d in r if d.get('track_id')})}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--cache',type=Path,required=True)
    parser.add_argument('--seconds',type=float,default=30)
    parser.add_argument('--fps',type=int,default=3)
    parser.add_argument('videos',nargs='+',type=Path)
    args=parser.parse_args()
    if not args.cache.exists():
        from cctv_tracker.openvino_yolox import OpenVinoYoloX
        cv2.setNumThreads(1)
        detector=OpenVinoYoloX(args.model,device='GPU')
        detector.detect(cv2.imencode('.jpg',np.zeros((64,64,3),np.uint8))[1].tobytes())
        cached=[]
        for path in args.videos:
            capture=cv2.VideoCapture(str(path)); native=capture.get(cv2.CAP_PROP_FPS)
            if not capture.isOpened() or native<=0:raise ValueError(f'Cannot read {path}')
            samples=[]; index=0; next_at=0
            try:
                while True:
                    ok,image=capture.read()
                    if not ok or index/native>=args.seconds:break
                    at=index/native;index+=1
                    if at+.001<next_at:continue
                    next_at+=1/args.fps
                    scale=min(1,640/max(image.shape[:2]))
                    image=cv2.resize(image,(round(image.shape[1]*scale),round(image.shape[0]*scale)))
                    jpeg=cv2.imencode('.jpg',image,[cv2.IMWRITE_JPEG_QUALITY,75])[1].tobytes()
                    started=time.perf_counter();result=detector.detect(jpeg)
                    samples.append({'at':at,'candidates':result['tracking_candidates'],
                                    'inference_ms':(time.perf_counter()-started)*1000})
                cached.append({'file':path.name,'native_fps':native,'sample_fps':args.fps,'samples':samples})
                print(f'Cached {path.name}: {len(samples)} fixed frames',flush=True)
            finally:capture.release()
        args.cache.parent.mkdir(parents=True,exist_ok=True)
        args.cache.write_text(json.dumps(cached,indent=2))
    cached=json.loads(args.cache.read_text());reports=[]
    for video in cached:
        tracker=Tracker(video['sample_fps'],3);display=DisplayTracks(1);measured=[];presented=[];details=[]
        for sample in video['samples']:
            rows=tracker.update([Detection(tuple(d['box']),d['confidence']) for d in sample['candidates']],sample['at'],'fixed-video')
            visible=[{'box':d.box,'confidence':d.confidence,'track_id':d.track_id} for d in rows if d.track_id or d.confidence>=.45]
            predictions=display.update(visible,round(sample['at']*1e9),'fixed-video',tracker.retained_ids)
            # Simulated 200ms presentation delay; predictions expire from the last real measurement.
            predictions=[p for p in predictions if p['valid_for_ms']>200]
            measured.append(visible);presented.append(visible+predictions)
            details.append({'at':sample['at'],'measured':visible,'predictions':predictions})
        reports.append({'file':video['file'],'measured':metrics(measured),'display_with_predictions':metrics(presented),'details':details,
                        'inference_p95_ms':round(float(np.percentile([s['inference_ms'] for s in video['samples']],95)),2)})
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps({'reports':reports,'limitation':'Fixed frames, unlabelled continuity only. Anonymous-ID counts are not true ID switches or accuracy.'},indent=2))
    print(json.dumps([{k:v for k,v in r.items() if k!='details'} for r in reports],indent=2),flush=True)


if __name__=='__main__':main()
