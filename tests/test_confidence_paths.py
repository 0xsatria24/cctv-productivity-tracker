"""Confidence routing contracts; synthetic boxes are not model-accuracy evidence."""
from contextlib import closing
from dataclasses import replace
from uuid import uuid4

import cv2
import numpy as np
import pytest

from cctv_tracker.config import Settings, Zone
from cctv_tracker.persistence import Database
from cctv_tracker.person_detection import DetectionTuning, decode_people, split_people, suppress_people
from cctv_tracker.pipeline import Pipeline
from cctv_tracker.replay_tracking import ReplayFrame, ReplayTracking
from cctv_tracker.sessions import SessionManager
from cctv_tracker.vision import Detection, Tracker, associate, frame_detections


def row(score=.95, x=.2):
    return {'box':[x,.2,x+.15,.8],'confidence':score}


class Detector:
    def __init__(self):
        self.packet={'detections':[row()]}

    def detect(self, _):
        return {**self.packet,'inference_ms':1}


@pytest.mark.parametrize('value',[0,.09,.5,True,'0.1',float('nan'),float('inf')])
def test_invalid_tracking_confidence(value):
    with pytest.raises(ValueError):
        DetectionTuning(tracking_confidence=value)


def test_decoder_low_route_is_explicit_and_public_suppression_stays_identical():
    p=np.zeros((3,85),np.float32)
    p[:,:4]=[[50,100,np.log(20),np.log(80)],[150,100,np.log(20),np.log(80)],[250,100,np.log(20),np.log(80)]]
    p[:,4]=1;p[:,5]=[.95,.2,.05]
    tuning=DetectionTuning()
    args=(p,np.zeros((3,2)),np.ones((3,1)),1,(0,0,400,400),(400,400),tuning)
    assert len(decode_people(*args)[0])==1
    boxes,scores=decode_people(*args,include_tracking=True)
    public,candidates=split_people(boxes,scores,(400,400),tuning)
    assert len(public)==len(candidates)==1
    assert public==suppress_people(*decode_people(*args),(400,400),tuning)
    assert candidates[0]['confidence']==pytest.approx(.2)


def test_low_full_frame_anchor_cannot_suppress_a_strong_tile_person():
    tuning=DetectionTuning(detail=True)
    boxes=[[10,10,110,210],[20,20,100,120],[220,20,260,150]]
    public,candidates=split_people(boxes,[.2,.95,.9],(400,400),tuning,full_frame_count=1)
    assert len(public)==2 and not candidates
    assert public==suppress_people(boxes[1:],[.95,.9],(400,400),tuning)


def test_candidate_budget_is_bounded_without_truncating_public_people():
    boxes=[[x,y,x+1,y+1] for y in range(0,100,4) for x in range(0,100,4)]
    public,candidates=split_people(boxes,[.2]*len(boxes),(100,100),DetectionTuning())
    assert public==[] and len(candidates)==128


def test_low_proposals_are_bounded_before_quadratic_suppression(monkeypatch):
    import cctv_tracker.person_detection as module
    original=module.suppress_people
    sizes=[]
    def checked(boxes,scores,*args,**kwargs):
        sizes.append(len(boxes))
        return original(boxes,scores,*args,**kwargs)
    monkeypatch.setattr(module,'suppress_people',checked)
    boxes=[[x,y,x+1,y+1] for y in range(0,128,2) for x in range(0,128,2)]
    public,candidates=split_people(boxes,[.2]*len(boxes),(128,128),DetectionTuning())
    assert sizes==[0,1024] and len(candidates)==128 and public==[]


@pytest.mark.parametrize('kind',['yolox','yolox-openvino'])
def test_both_detector_transports_keep_low_boxes_out_of_public_count(monkeypatch,kind):
    from cctv_tracker.engine import create_detector
    detector=create_detector(kind)
    detector.session=object()
    detector.grid=np.zeros((2,2));detector.strides=np.ones((2,1))
    output=np.zeros((2,85),np.float32)
    output[:,:4]=[[80,160,np.log(40),np.log(120)],[400,160,np.log(40),np.log(120)]]
    output[:,4]=1;output[:,5]=[.95,.2]
    monkeypatch.setattr(detector,'_infer',lambda blob:output.copy())
    jpeg=cv2.imencode('.jpg',np.zeros((400,400,3),np.uint8))[1].tobytes()
    result=detector.detect(jpeg)
    assert result['count']==len(result['detections'])==1
    assert result['tracking_candidate_count']==len(result['tracking_candidates'])==1
    assert result['tracking_candidates'][0]['confidence']==pytest.approx(.2)


@pytest.mark.parametrize('score',[.1004,.2496])
def test_internal_score_precision_preserves_bytetrack_boundary_association(score):
    _,candidates=split_people([[40,40,100,180]],[score],(400,400),DetectionTuning())
    tracker=Tracker(5,1)
    first=tracker.update([Detection(tuple(candidates[0]['box']),.95)],0,'g')[0]
    weak=tracker.update(frame_detections({'detections':[],'tracking_candidates':candidates}),.2,'g')[0]
    assert weak.track_id==first.track_id
    assert weak.confidence==pytest.approx(score) and weak.tracking_only


def test_weak_continuation_keeps_identity_and_freezes_both_ends_of_gap():
    replay,detector,rid=ReplayTracking(),Detector(),str(uuid4())
    def feed(seq,score):
        detector.packet={'detections':[row()]} if score>.45 else {'detections':[],'tracking_candidates':[row(score)]}
        return replay.process(detector,b'',ReplayFrame(rid,0,seq,(seq-1)*.2))
    sid=feed(1,.95)['detections'][0]['session_id']
    assert feed(2,.95)['detections'][0]['accumulated_duration_us']==200_000
    weak=feed(3,.2)
    session=next(s for s in weak['sessions'] if s['session_id']==sid)
    assert weak['count']==0 and weak['detections']==[]
    assert session['status']=='ACTIVE' and session['evidence_state']=='WEAK'
    assert session['accumulated_duration_us']==200_000
    assert weak['tracking']['matched_tracking_candidates']==1
    assert weak['tracking']['public_measured_count']==0
    strong=feed(4,.95)['detections'][0]
    assert strong['session_id']==sid and strong['accumulated_duration_us']==200_000
    assert feed(5,.95)['detections'][0]['accumulated_duration_us']==400_000


@pytest.mark.parametrize('score',[.2,.65])
def test_tracking_only_never_starts_sessions_or_charges_zones_even_at_high_score(score):
    settings=replace(Settings(),zones=(Zone('desk','Meja',((0,0),(1,0),(1,1),(0,1))),))
    detector=Detector();detector.packet={'detections':[],'tracking_candidates':[row(score)]}
    replay,rid=ReplayTracking(settings),str(uuid4())
    for seq in range(1,9):
        packet=replay.process(detector,b'',ReplayFrame(rid,0,seq,(seq-1)*.2))
    assert packet['count']==0 and packet['sessions']==[]
    flagged=frame_detections(detector.packet)
    assert flagged[0].tracking_only
    assert associate(flagged,settings.zones,settings.rules)['desk'][0]=='UNKNOWN'
    manager=SessionManager(settings,continuation_confidence=.1)
    assert manager.update(flagged,0,0,'g')[0][1] is None


def test_weak_measurements_cannot_keep_identity_alive_past_strong_evidence_gap():
    replay,detector,rid=ReplayTracking(),Detector(),str(uuid4())
    first=replay.process(detector,b'',ReplayFrame(rid,0,1,0))['detections'][0]['session_id']
    detector.packet={'detections':[],'tracking_candidates':[row(.2)]}
    for seq in range(2,9):
        packet=replay.process(detector,b'',ReplayFrame(rid,0,seq,(seq-1)*.2))
    assert next(s for s in packet['sessions'] if s['session_id']==first)['status']=='LOST'
    detector.packet={'detections':[row()]}
    returned=replay.process(detector,b'',ReplayFrame(rid,0,9,1.6))['detections'][0]
    assert returned['session_id']!=first and returned['accumulated_duration_us']==0


def test_tracking_candidate_cannot_recover_a_lost_session():
    replay,detector,rid=ReplayTracking(),Detector(),str(uuid4())
    first=replay.process(detector,b'',ReplayFrame(rid,0,1,0))['detections'][0]['session_id']
    detector.packet={'detections':[]}
    replay.process(detector,b'',ReplayFrame(rid,0,2,.2))
    detector.packet={'detections':[],'tracking_candidates':[row(.2)]}
    packet=replay.process(detector,b'',ReplayFrame(rid,0,3,.4))
    assert len(packet['sessions'])==1 and packet['sessions'][0]['session_id']==first
    assert packet['sessions'][0]['status']=='LOST' and packet['sessions'][0]['accumulated_duration_us']==0


@pytest.mark.parametrize('failure',['geometry_jump','duplicate_id'])
def test_raw_id_alone_cannot_continue_a_session_with_weak_evidence(failure):
    manager=SessionManager(Settings(),continuation_confidence=.1)
    original=manager.update([Detection((.2,.2,.35,.8),.95,'id')],0,0,'g')[0][1]
    boxes=[Detection((.7,.2,.85,.8),.2,'id',tracking_only=True)] if failure=='geometry_jump' else [
        Detection((.2,.2,.35,.8),.2,'id',tracking_only=True),
        Detection((.21,.2,.36,.8),.2,'id',tracking_only=True)]
    bindings=manager.update(boxes,200_000,200_000_000,'g')
    assert all(session is None for _,session in bindings)
    assert original.status=='LOST' and original.accumulated_ns==0


def test_crossing_with_low_candidates_never_transfers_public_session_ownership():
    replay,detector,rid=ReplayTracking(),Detector(),str(uuid4())
    owners={}
    for step in range(41):
        at=step/5
        people=[('A',row(.95,.1+.05*at)),('B',row(.95,.65-.05*at))]
        public=[];candidates=[];labels=[]
        for label,person in people:
            if step%3==1 and label=='A':
                candidates.append({**person,'confidence':.2})
            else:
                public.append(person);labels.append(label)
        detector.packet={'detections':public,'tracking_candidates':candidates}
        packet=replay.process(detector,b'',ReplayFrame(rid,0,step+1,at))
        assert packet['count']==len(public)
        for label,detection in zip(labels,packet['detections']):
            sid=detection['session_id']
            if sid:
                owners.setdefault(sid,label)
                assert owners[sid]==label


def test_pipeline_persists_frozen_identity_and_excludes_tracking_only_rows(tmp_path):
    settings=replace(Settings(),database=tmp_path/'confidence.sqlite3',
                     zones=(Zone('desk','Meja',((0,0),(1,0),(1,1),(0,1))),))
    with closing(Database(settings.database)) as db:
        pipeline=Pipeline(settings,db,1_000_000,'SYNTHETIC_REPLAY','a'*64,{})
        try:
            strong=frame_detections({'detections':[row()]})
            sid=pipeline.feed(strong,1_000_000,0,1,'g')['detections'][0]['session_id']
            pipeline.feed(strong,1_200_000,200_000_000,2,'g')
            weak=pipeline.feed(frame_detections({'detections':[],'tracking_candidates':[row(.2)]}),1_400_000,400_000_000,3,'g')
            assert weak['detections']==[] and weak['zones'][0]['state']=='UNKNOWN'
            stored=db.conn.execute('SELECT * FROM person_sessions WHERE session_id=?',(sid,)).fetchone()
            assert stored['accumulated_duration_us']==200_000 and stored['status']=='ACTIVE'
            returned=pipeline.feed(strong,1_600_000,600_000_000,4,'g')['detections'][0]
            assert returned['session_id']==sid and returned['accumulated_duration_us']==200_000
            weak_public=pipeline.feed(frame_detections({'detections':[row(.47)]}),1_800_000,800_000_000,5,'g')['detections'][0]
            assert weak_public['session_id']==sid and weak_public['evidence_state']=='WEAK'
            assert weak_public['workstation_times']==[] and weak_public['accumulated_duration_us']==200_000
        finally:
            report=pipeline.finish()
        assert report['workstations'][0]['occupied_us']==0


def test_tracking_only_cannot_feed_reid_gallery():
    from cctv_tracker.reid.config import ReIdRules
    from cctv_tracker.reid.crops import make_crops
    from cctv_tracker.reid.types import FrameToken
    from reid_helpers import jpeg
    low=Detection((.2,.2,.4,.8),.9,'track',tracking_only=True)
    samples,rejections=make_crops(jpeg(),[low],FrameToken('camera','run','generation',1,0,0),ReIdRules())
    assert samples==[] and rejections[0]['reason']=='LOW_CONFIDENCE'


def test_weak_tail_cannot_extend_reid_recovery_window():
    from cctv_tracker.reid.config import ReIdRules
    from cctv_tracker.reid.runtime import ReIdRuntime
    manager=SessionManager(Settings(),continuation_confidence=.1)
    measured=Detection((.2,.2,.35,.8),.95,'track')
    old=manager.update([measured],0,0,'g')[0][1]
    weak=Detection(measured.box,.2,'track',tracking_only=True)
    manager.update([weak],800_000,800_000_000,'g')
    manager.update([],1_200_000,1_200_000_000,'g')
    candidate=manager.update([measured],2_500_000,2_500_000_000,'g',recover=False)[0][1]
    runtime=ReIdRuntime(ReIdRules(max_gap_seconds=2))
    assert old.last_ns==800_000_000 and old.last_strong_ns==0
    assert runtime._short_occlusion_score(old,candidate,measured,2_500_000_000) is None
