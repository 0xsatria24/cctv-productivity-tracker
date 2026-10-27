from contextlib import closing
import time

import pytest
from fastapi.testclient import TestClient

from cctv_tracker.api import create_app
from cctv_tracker.aruco import marker_png
from cctv_tracker.config import Rules, Settings, Zone
from cctv_tracker.dashboard import ReplayController
from cctv_tracker.live import LiveController
from cctv_tracker.persistence import Database
from cctv_tracker.pipeline import Pipeline
from cctv_tracker.vision import Detection
from test_live import FixtureDetector, profile, wait_for


def area_settings(tmp_path):
    return Settings(database=tmp_path/'area.sqlite3',
                    zones=(Zone('desk','Meja',((0,0),(1,0),(1,1),(0,1))),),
                    rules=Rules(occupied_confirm_seconds=.5,empty_confirm_seconds=.5))


def test_area_mode_bypasses_person_identity_and_matches_committed_zone_totals(tmp_path,monkeypatch):
    import cctv_tracker.pipeline as module
    def forbidden(*args,**kwargs):
        raise AssertionError('Workstation mode must bypass person tracking and ReID')
    for name in ('Tracker','SessionManager','ReIdRuntime'):
        monkeypatch.setattr(module,name,forbidden)
    settings=area_settings(tmp_path)
    with closing(Database(settings.database)) as db:
        pipeline=Pipeline(settings,db,1_000_000,'WEBCAM_LIVE','f'*64,{},area_mode=True,live_events=True)
        seq=0
        def feed(at,rows,unavailable=None):
            nonlocal seq
            seq+=1
            return pipeline.feed(rows,1_000_000+round(at*1e6),round(at*1e9),seq,'camera',unavailable)
        try:
            for at in (0,.5,1,1.5,2):
                packet=feed(at,[Detection((.1,.1,.8,.9),.95)])
            row=packet['workstations'][0]
            assert row['occupied_us']==1_500_000
            assert packet['sessions']==[] and packet['reid']['mode']=='off'
            assert packet['tracking']['algorithm'] is None
            assert packet['detections'][0]['session_id'] is None
            for at in (2.5,3,3.5):
                packet=feed(at,[])
            before=packet['workstations'][0]
            assert before['occupied_us']==1_500_000 and before['empty_us']==500_000
            stale=feed(10,[],'FRAME_STALE')['workstations'][0]
            assert stale['state']=='UNKNOWN' and stale['occupied_us']==before['occupied_us']
            assert stale['empty_us']==before['empty_us']
            report=db.report(pipeline.start,pipeline.last_utc,run_id=pipeline.writer.run_id)['workstations'][0]
            assert report['occupied_us']==stale['occupied_us'] and report['empty_us']==stale['empty_us']
            assert db.conn.execute('SELECT COUNT(*) FROM person_sessions').fetchone()[0]==0
            ignored=pipeline.feed([],1_000_001,1,1,'camera')
            assert ignored['ignored'] and ignored['workstations'][0]==stale
        finally:
            pipeline.finish()


def test_live_aruco_uses_real_decoder_and_reconnect_requires_new_confirmation(tmp_path):
    settings=area_settings(tmp_path)
    jpeg=marker_png(7)
    with closing(Database(settings.database)) as db:
        pipeline=Pipeline(settings,db,1_000_000,'RTSP_LIVE','f'*64,{},area_mode=True,
                          markers=[{'marker_id':7,'label':'Operator uji'}])
        try:
            for seq in range(1,6):
                at=(seq-1)*.5
                packet=pipeline.feed([Detection((0,0,1,1),.95)],1_000_000+round(at*1e6),round(at*1e9),seq,'first',frame_jpeg=jpeg)
            row=packet['workstations'][0]
            assert packet['aruco']['markers'][0]['marker_id']==7
            assert row['checkin']['state']=='VERIFIED_MARKER'
            assert row['checkin']['registered']['label']=='Operator uji'
            lost=pipeline.feed([],3_500_000,2_500_000_000,6,'first','FRAME_STALE')['workstations'][0]
            assert lost['occupied_us']==row['occupied_us'] and lost['checkin']['state']!='VERIFIED_MARKER'
            restarted=pipeline.feed([Detection((0,0,1,1),.95)],4_000_000,3_000_000_000,1,'second',frame_jpeg=jpeg)['workstations'][0]
            assert restarted['checkin']['registered'] is None
            assert restarted['occupied_us']==row['occupied_us']
        finally:
            pipeline.finish()


def test_live_area_transport_preserves_final_timer_after_stop(tmp_path):
    settings=Settings(database=tmp_path/'source.sqlite3')
    controller=LiveController(settings,FixtureDetector())
    config={**profile(),'analysis_mode':'workstation','markers':[]}
    controller.save_calibration('WEBCAM_LIVE',config)
    try:
        started=controller.start('WEBCAM_LIVE',camera_key=config['camera_key'])
        wait_for(lambda:controller.snapshot()['status']=='RUNNING')
        for seq in range(1,5):
            packet=controller.submit(marker_png(7),started['session_id'],seq)
            time.sleep(.12)
        assert packet['analysis_mode']=='workstation' and packet['workstations'][0]['occupied_us']>0
        before=packet['workstations'][0]['occupied_us']
        controller.shutdown()
        assert controller.snapshot()['workstations'][0]['occupied_us']>=before
        with closing(Database(controller.settings.database)) as db:
            assert db.conn.execute('SELECT COUNT(*) FROM person_sessions').fetchone()[0]==0
    finally:
        controller.shutdown()


def test_area_calibration_api_persists_mode_and_rejects_ambiguous_marker_registry(tmp_path):
    settings=Settings(database=tmp_path/'api.sqlite3')
    with closing(Database(settings.database)):
        pass
    headers={'Authorization':'Bearer '+'t'*32}
    config={**profile(),'source':'WEBCAM_LIVE','analysis_mode':'workstation','markers':[{'marker_id':7,'label':'Operator'}]}
    with TestClient(create_app(settings.database,'t'*32,controller=ReplayController(settings))) as client:
        response=client.post('/pilot/v1/live/calibration',json=config,headers=headers)
        assert response.status_code==200
        saved=response.json()['calibrations']['WEBCAM_LIVE']
        assert saved['analysis_mode']=='workstation' and saved['markers']==config['markers']
        assert client.post('/pilot/v1/live/calibration',json={**config,'markers':config['markers']*2},headers=headers).status_code==422
        assert client.post('/pilot/v1/live/calibration',json={**config,'analysis_mode':'invalid'},headers=headers).status_code==422
    restored=LiveController(settings,FixtureDetector())
    assert restored.snapshot()['calibrations']['WEBCAM_LIVE']['analysis_mode']=='workstation'
    restored.shutdown()
