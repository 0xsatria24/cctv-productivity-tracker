from contextlib import closing
from uuid import uuid4

import cv2
import numpy as np
from fastapi.testclient import TestClient

from cctv_tracker.api import create_app
from cctv_tracker.config import Settings
from cctv_tracker.dashboard import ReplayController
from cctv_tracker.persistence import Database


def test_replay_calibration_auth_revision_limits_and_accounting_isolation(tmp_path, monkeypatch):
    from cctv_tracker.webcam import WebcamDetector
    monkeypatch.setattr(WebcamDetector,'detect',lambda self,data:{'detections':[{'box':[.2,.2,.4,.8],'confidence':.95}],'count':1,'inference_ms':1})
    path=tmp_path/'replay.sqlite3'
    with closing(Database(path)) as db:
        before={name:db.conn.execute(f'SELECT COUNT(*) FROM {name}').fetchone()[0] for name in ('engine_runs','zone_intervals','person_sessions')}
    token='t'*32
    headers={'Authorization':'Bearer '+token}
    rid=str(uuid4())
    url=f'/pilot/v1/replay/{rid}/calibration'
    values={'expected_revision':0,'association':'bbox_overlap','zones':[{'id':'desk','name':'Meja','polygon':[[.1,.1],[.9,.1],[.9,.9],[.1,.9]]}]}
    with TestClient(create_app(path,token,controller=ReplayController(Settings(database=path)))) as client:
        assert client.get(url).status_code==401
        assert client.put(url,json=values).status_code==401
        assert client.put(url,json=values,headers={**headers,'Origin':'https://evil.example'}).status_code==403
        assert client.get(url,headers=headers).json()['calibration_revision']==0
        assert client.put(url,content=b'x'*32769,headers=headers).status_code==413
        assert client.put(url,content=b'{invalid',headers=headers).status_code==422
        assert client.put(url,json={**values,'zones':[{}]},headers=headers).status_code==422
        result=client.put(url,json=values,headers=headers)
        assert result.status_code==200 and result.json()['calibration_revision']==1
        assert client.put(url,json=values,headers=headers).status_code==409
        assert client.get(url,headers=headers).json()['zones']==values['zones']
        jpeg=cv2.imencode('.jpg',np.zeros((240,320,3),dtype=np.uint8))[1].tobytes()
        envelope={**headers,'Content-Type':'image/jpeg','X-Replay-Id':rid,'X-Replay-Generation':'0','X-Replay-Sequence':'1','X-Replay-Time':'0'}
        assert client.post('/pilot/v1/replay/frame',content=jpeg,headers=envelope).status_code==409
        response=client.post('/pilot/v1/replay/frame',content=jpeg,headers={**envelope,'X-Replay-Calibration':'1'})
        assert response.status_code==200,response.text
        assert response.json()['workstations'][0]['zone_id']=='desk'
        assert not response.json()['recorded'] and not response.json()['duration_accounting']
        assert client.get('/pilot/v1/replay/invalid/calibration',headers=headers).status_code==422
    with closing(Database(path,migrate=False)) as db:
        assert {name:db.conn.execute(f'SELECT COUNT(*) FROM {name}').fetchone()[0] for name in before}==before
