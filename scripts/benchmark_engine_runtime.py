"""Single-camera runtime check using a local RTSP replay, without a GUI."""
import argparse
import json
from pathlib import Path
import time

from cctv_tracker.config import Settings
from cctv_tracker.engine import create_detector, create_live_engine
from cctv_tracker.rtsp import rtsp_camera_key


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url',required=True)
    parser.add_argument('--device',choices=['CPU','GPU'],default='CPU')
    parser.add_argument('--model',type=Path,required=True)
    parser.add_argument('--seconds',type=int,default=30)
    parser.add_argument('--output',type=Path,required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    settings = Settings(database=args.output/'runtime.sqlite3')
    engine = create_live_engine(settings,create_detector('yolox-openvino',args.device,args.model))
    key = rtsp_camera_key(args.url)
    engine.save_calibration('RTSP_LIVE',{'width':640,'height':360,'camera_key':key,
        'zones':[{'id':'test','name':'Local replay test','polygon':[[0,0],[1,0],[1,1],[0,1]]}],
        'rules':{'occupied_confirm_seconds':2,'empty_confirm_seconds':5,'max_evidence_gap_seconds':3}})
    try:
        engine.start('RTSP_LIVE',args.url)
        deadline = time.perf_counter()+90
        while engine.snapshot()['processed'] < 5:
            state = engine.snapshot()
            if state['status']=='FAILED' or time.perf_counter()>deadline:
                raise RuntimeError('Runtime did not reach stable processing')
            time.sleep(.2)
        before, started = engine.snapshot()['processed'],time.perf_counter()
        while time.perf_counter()-started < args.seconds:
            if engine.snapshot()['status']=='FAILED':
                raise RuntimeError('Runtime failed during measurement')
            time.sleep(.2)
        state = engine.snapshot()
        result = {'device':args.device,'seconds':round(time.perf_counter()-started,2),
                  'processed_fps':round((state['processed']-before)/(time.perf_counter()-started),2),
                  'performance':state['performance'],'limitation':'Local RTSP replay on the current host, not a mini-PC capacity guarantee.'}
        (args.output/'summary.json').write_text(json.dumps(result,indent=2))
        print(json.dumps(result),flush=True)
    finally:
        engine.shutdown()


if __name__=='__main__':
    main()
