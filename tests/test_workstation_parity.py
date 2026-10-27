from contextlib import closing
from dataclasses import asdict
from copy import deepcopy
from uuid import uuid4
from types import SimpleNamespace
import time

import pytest

from cctv_tracker.config import Rules, Settings, Zone
from cctv_tracker.api import LiveRulesInput
from cctv_tracker.live import LiveController
from cctv_tracker.persistence import Database
from cctv_tracker.pipeline import Pipeline
from cctv_tracker.positioning import PositionCalibration
from cctv_tracker.replay_tracking import ReplayFrame, ReplayTracking
from cctv_tracker.vision import frame_detections
from cctv_tracker.workstation_engine import workstation_policy
from cctv_tracker.rtsp import rtsp_camera_key
from cctv_tracker.aruco import marker_png
from test_aruco_workstation import marker
from test_live import FixtureDetector
from test_live import profile,wait_for


class Reader:
    rows = []
    fail = False

    def detect(self, _jpeg):
        if self.fail:
            raise RuntimeError('Injected marker decoder failure')
        return {'status':'READY','markers':deepcopy(self.rows)}


@pytest.mark.parametrize('association',['bbox_overlap','footpoint'])
@pytest.mark.parametrize('registered',[False,True])
def test_replay_and_live_share_area_timer_and_marker_outcomes(tmp_path,association,registered):
    zone={'id':'desk','name':'Meja','polygon':[[.1,.1],[.9,.1],[.9,.9],[.1,.9]]}
    registry=[{'marker_id':7,'label':'Operator'}] if registered else []
    settings=Settings(database=tmp_path/'live.sqlite3',zones=(Zone('desk','Meja',tuple(map(tuple,zone['polygon']))),),
                      rules=Rules(occupied_confirm_seconds=.5,empty_confirm_seconds=.5,max_evidence_gap_seconds=1),
                      position=PositionCalibration(mode=association))
    reader=Reader()
    replay=ReplayTracking(settings,aruco_reader=reader)
    rid=str(uuid4())
    replay.configure(rid,{'expected_revision':0,'zones':[zone],'association':association,'markers':registry})
    detector=FixtureDetector()
    person={'box':[.2,.2,.8,.8],'confidence':.95}
    weak={**person,'confidence':.47}
    second={'box':[.65,.2,.85,.8],'confidence':.95}
    samples=[
        (0,[person],[marker()]),(.5,[person],[marker()]),(1,[person],[marker()]),
        (1.5,[person],[marker()]),(2,[weak],[marker()]),(2.5,[],[marker()]),
        (3,[],[]),(3.5,[],[]),(4,[person,second],[marker()]),
        (4.5,[person,second],[marker()]),(5,[person],[marker(),marker(8)]),
        (5.5,[person],[marker(30)]),(6,[person],[]),
        (9,[person],[marker()]),(9.5,[person],[marker()]),(10,[person],[marker()]),
        (10.5,[person],[marker()]),(11,[person],[marker()]),
    ]
    fields=('state','count','reason','occupied_us','empty_us','unknown_us','observed_us','checkin')
    with closing(Database(settings.database)) as db:
        live=Pipeline(settings,db,1_000_000,'WEBCAM_LIVE','f'*64,{},area_mode=True,markers=registry)
        live.marker_reader=reader
        try:
            for seq,(at,people,markers) in enumerate(samples,1):
                detector.rows=people
                detector.candidates=[person] if at==2 else []
                reader.rows=markers
                replayed=replay.process(detector,b'fixture',ReplayFrame(rid,0,seq,at,1),'workstation')
                current=live.feed(frame_detections(detector.detect(b'fixture')),1_000_000+round(at*1e6),
                                  round(at*1e9),seq,'generation-0',frame_jpeg=b'fixture')
                assert {key:replayed['workstations'][0][key] for key in fields}=={
                    key:current['workstations'][0][key] for key in fields}, (at,association)
                assert replayed['aruco']['status']==current['aruco']['status']
                assert replayed['aruco']['dictionary']==current['aruco']['dictionary']
                assert replayed['sessions']==current['sessions']==[]
            reader.fail=True
            last=len(samples)+1
            replayed=replay.process(detector,b'fixture',ReplayFrame(rid,0,last,11.5,1),'workstation')
            current=live.feed(frame_detections(detector.detect(b'fixture')),12_500_000,11_500_000_000,last,'generation-0',frame_jpeg=b'fixture')
            assert replayed['aruco']==current['aruco']
            assert replayed['workstations'][0]['checkin']==current['workstations'][0]['checkin']
            reader.fail=False
            reader.rows=[marker()]
            replayed=replay.process(detector,b'fixture',ReplayFrame(rid,1,last+1,12,1),'workstation')
            current=live.feed(frame_detections(detector.detect(b'fixture')),13_000_000,12_000_000_000,1,'generation-1',frame_jpeg=b'fixture')
            # Replay skips the seek boundary; live keeps its outage as unknown.
            for key in ('state','count','occupied_us','empty_us','checkin'):
                assert replayed['workstations'][0][key]==current['workstations'][0][key]
            assert current['workstations'][0]['checkin']['registered'] is None
        finally:
            live.finish()


def test_live_and_replay_publish_the_same_configured_policy(tmp_path):
    settings=Settings(database=tmp_path/'configured.sqlite3',rules=Rules(occupied_confirm_seconds=.7,empty_confirm_seconds=.8,max_evidence_gap_seconds=1.5))
    live=LiveController(settings,FixtureDetector())
    try:
        assert live.snapshot()['workstation_policy']==workstation_policy(ReplayTracking(settings).settings)
    finally:
        live.shutdown()


def test_live_api_defaults_follow_replay_domain_defaults():
    assert LiveRulesInput().model_dump()==asdict(Rules())


def test_rtsp_workstation_observations_follow_shared_cadence(tmp_path):
    class Capture:
        reads=0
        def __init__(self,*args):
            self.started=time.perf_counter()
            self.process=SimpleNamespace(is_alive=lambda:True)
        def read(self,timeout=0):
            time.sleep(.02)
            type(self).reads+=1
            return {'jpeg':jpeg,'monotonic_ns':time.perf_counter_ns(),'generation':'fixture'}
        def close(self):
            pass
    class Detector(FixtureDetector):
        def __init__(self):
            super().__init__()
            self.calls=[]
        def detect(self,jpeg):
            self.calls.append(time.perf_counter())
            return super().detect(jpeg)
    jpeg=marker_png(7)
    detector=Detector()
    url='rtsp://127.0.0.1:8554/test-fixture'
    controller=LiveController(Settings(database=tmp_path/'cadence.sqlite3'),detector,capture_factory=Capture)
    controller.save_calibration('RTSP_LIVE',{**profile(),'camera_key':rtsp_camera_key(url),'analysis_mode':'workstation','markers':[]})
    try:
        controller.start('RTSP_LIVE',url)
        wait_for(lambda:controller.snapshot()['processed']>=3)
        controller.shutdown()
        samples=detector.calls[1:]  # Exclude model warm-up.
        assert len(samples)>=3
        assert all(right-left>=.45 for left,right in zip(samples,samples[1:]))
        assert Capture.reads>len(samples)
    finally:
        controller.shutdown()
