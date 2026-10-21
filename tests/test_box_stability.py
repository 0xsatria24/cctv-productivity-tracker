from concurrent.futures import ThreadPoolExecutor
from threading import Event
import time

import pytest

from cctv_tracker.config import Rules,Zone
from cctv_tracker.display_tracks import DisplayTracks
from cctv_tracker.domain.occupancy import State
from cctv_tracker.inference import FairDetector
from cctv_tracker.observation_view import observation_view
from cctv_tracker.vision import Detection,Tracker,associate


BOX=(.1,.1,.4,.8)


def test_short_lost_track_recovers_weak_evidence_without_promoting_confidence():
    tracker=Tracker(5,3)
    original=tracker.update([Detection(BOX,.9)],0,'camera')[0].track_id
    assert tracker.update([],.2,'camera')==[]
    weak=tracker.update([Detection(BOX,.2)],.4,'camera')
    assert weak[0].track_id==original
    assert weak[0].confidence==pytest.approx(.2)
    zone=Zone('desk','Desk',((0,0),(1,0),(1,1),(0,1)))
    assert associate(weak,(zone,),Rules())['desk'][0]==State.UNKNOWN
    disabled=Tracker(5,3,recovery_seconds=0)
    disabled.update([Detection(BOX,.9)],0,'camera');disabled.update([],.2,'camera')
    assert disabled.update([Detection(BOX,.2)],.4,'camera')[0].track_id is None
    tracker.update([],.6,'camera')
    assert tracker.update([Detection(BOX,.2)],1.6,'camera')[0].track_id is None


def test_weak_recovery_does_not_guess_between_overlapping_workers():
    tracker=Tracker(5,3)
    other=(.25,.1,.55,.8)
    rows=tracker.update([Detection(BOX,.9),Detection(other,.9)],0,'camera')
    assert len({r.track_id for r in rows})==2
    tracker.update([],.2,'camera')
    assert tracker.update([Detection((.17,.1,.47,.8),.2)],.4,'camera')[0].track_id is None


def test_individual_track_expires_by_elapsed_time_while_other_worker_remains():
    tracker=Tracker(5,3)
    other=Detection((.6,.1,.9,.8),.9)
    original=tracker.update([Detection(BOX,.9),other],0,'camera')[0].track_id
    for i in range(1,17):tracker.update([other],i*.2,'camera')
    assert original not in tracker.retained_ids
    tracker.update([Detection(BOX,.9),other],3.4,'camera')
    assert tracker.update([Detection(BOX,.9),other],3.6,'camera')[0].track_id!=original


def measured(identifier='x',box=BOX):
    return {'track_id':identifier,'box':box,'confidence':.9,
            'activity':{'label':'Working','tracked_elapsed_us':2_000_000}}


def test_display_prediction_is_separate_bounded_and_expires_without_new_evidence():
    display=DisplayTracks(1)
    assert display.update([measured()],0,'a',{'x'})==[]
    predictions=display.update([],400_000_000,'a',{'x'})
    assert predictions[0]['evidence']=='PREDICTED'
    assert predictions[0]['activity']['label'] is None
    assert 'confidence' not in predictions[0]
    packet={'monotonic_ns':400_000_000,'published_monotonic_ns':410_000_000,'sequence':2,'utc_ms':0,
            'observation':{'count':0,'detections':[],'display_predictions':predictions}}
    view=observation_view(packet,600_000_000)['observation']
    assert view['count']==0 and view['detections']==[]
    assert view['display_predictions'][0]['valid_for_ms']==400
    assert observation_view(packet,1_100_000_000)['observation']['display_predictions']==[]
    assert display.update([],1_000_000_000,'a',{'x'})==[]
    display.update([measured()],1_100_000_000,'a',{'x'})
    assert display.update([],1_200_000_000,'new-generation',{'x'})==[]
    display.update([measured()],1_300_000_000,'new-generation',{'x'})
    assert display.update([],1_400_000_000,'new-generation',set())==[]
    assert DisplayTracks(0).update([],1,'a',set())==[]


def test_prediction_clamps_fast_motion_and_state_size():
    display=DisplayTracks(1)
    display.update([measured()],0,'a',{'x'})
    display.update([measured(box=(.7,.1,1,.8))],100_000_000,'a',{'x'})
    prediction=display.update([],500_000_000,'a',{'x'})[0]
    assert all(0<=v<=1 for v in prediction['box'])
    assert prediction['box'][2]-prediction['box'][0]==pytest.approx(.3)
    rows=[measured(str(i)) for i in range(200)]
    display.update(rows,600_000_000,'a',{str(i) for i in range(200)})
    assert len(display.tracks)==128


def test_scheduler_chooses_latest_frame_only_after_obtaining_model_turn():
    entered,release=Event(),Event();seen=[]
    class Detector:
        def detect(self,jpeg):
            seen.append(jpeg)
            if jpeg==b'first':entered.set();assert release.wait(3)
            return {}
    scheduler=FairDetector(Detector())
    item={'jpeg':b'old','monotonic_ns':time.perf_counter_ns()}
    latest={}
    with ThreadPoolExecutor(2) as pool:
        first=pool.submit(scheduler.detect,b'first');assert entered.wait(3)
        second=pool.submit(scheduler.detect_latest,item,lambda:latest.get('item'),3)
        deadline=time.perf_counter()+3
        while scheduler.scheduling_snapshot()['pending']<2 and time.perf_counter()<deadline:time.sleep(.01)
        latest['item']={'jpeg':b'new','monotonic_ns':time.perf_counter_ns()}
        release.set();first.result(timeout=3);result,selected=second.result(timeout=3)
    assert selected['jpeg']==b'new' and seen==[b'first',b'new']
    assert scheduler.scheduling_snapshot()['refreshed_frames']==1
    assert scheduler.scheduling_snapshot()['pending']==0
    with pytest.raises(ValueError,match='stale'):
        scheduler.detect_latest({'jpeg':b'stale','monotonic_ns':0},lambda:None,.1)
    assert seen==[b'first',b'new']
    assert scheduler.scheduling_snapshot()['pending']==0
