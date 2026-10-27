from uuid import uuid4

import cv2
import numpy as np
import pytest

from cctv_tracker.aruco import ArucoReader, MarkerCheckIns, marker_png, validate_registry
from cctv_tracker.config import Zone
from cctv_tracker.vision import Detection
from cctv_tracker.replay_tracking import ReplayFrame, ReplayTracking, ReplayConflict

ZONE = {'id': 'desk', 'name': 'Meja A', 'polygon': [[.1,.1],[.9,.1],[.9,.9],[.1,.9]]}
REGISTRY = [{'marker_id': 7, 'label': 'Pekerja A'}, {'marker_id': 8, 'label': 'Pekerja B'}]


def marker(identifier=7, center=(.5,.5)):
    return {'marker_id': identifier, 'center': center, 'corners': []}


class Reader:
    markers = [marker()]
    def detect(self, _):
        return {'status': 'READY', 'markers': self.markers}


class Detector:
    rows = [{'box': [.3,.2,.6,.8], 'confidence': .95}]
    def detect(self, _):
        return {'detections': self.rows, 'count': len(self.rows), 'inference_ms': 1}


def fixture():
    reader, detector = Reader(), Detector()
    replay, rid = ReplayTracking(aruco_reader=reader), str(uuid4())
    replay.configure(rid, {'expected_revision': 0, 'zones': [ZONE], 'association': 'bbox_overlap', 'markers': REGISTRY})
    def run(seq, generation=0, at=None):
        return replay.process(detector, b'', ReplayFrame(rid, generation, seq, (seq-1)*.5 if at is None else at, 1), 'workstation')
    return replay, rid, reader, detector, run


@pytest.mark.parametrize('identifier', [0,7,49])
def test_downloaded_marker_decodes_to_exact_identifier(identifier):
    reader = ArucoReader()
    result = reader.detect(marker_png(identifier))
    assert [m['marker_id'] for m in result['markers']] == [identifier]
    image = cv2.imdecode(np.frombuffer(marker_png(identifier), np.uint8), 0)
    image[56:180,56:456] = 255
    assert reader.detect(cv2.imencode('.png', image)[1].tobytes())['markers'] == []


def test_workstation_bypasses_tracker_and_reid_and_marker_loss_does_not_reset_area_timer(monkeypatch):
    import cctv_tracker.replay_tracking as module
    def forbidden(*args, **kwargs):
        raise AssertionError('Area analysis must not instantiate person tracking')
    monkeypatch.setattr(module, 'Tracker', forbidden)
    monkeypatch.setattr(module, 'ReIdRuntime', forbidden)
    replay, rid, reader, detector, run = fixture()
    for seq in range(1,9):
        packet = run(seq)
    station = packet['workstations'][0]
    assert station['checkin']['registered']['label'] == 'Pekerja A'
    assert station['checkin']['state'] == 'VERIFIED_MARKER'
    assert replay.streams[rid].tracker is None and packet['reid']['mode'] == 'off'
    assert not packet['recorded'] and not packet['duration_accounting']
    reader.markers = []
    missing = run(9)['workstations'][0]
    assert missing['occupied_us'] > station['occupied_us']
    assert missing['checkin']['registered']['label'] == 'Pekerja A'
    assert missing['checkin']['state'] == 'UNREGISTERED'
    reader.markers = [marker(8)]
    for seq in range(10,13):
        switched = run(seq)['workstations'][0]
    assert switched['checkin']['registered']['label'] == 'Pekerja B'
    assert switched['occupied_us'] > missing['occupied_us']
    detector.rows = []
    reader.markers = []
    for seq in range(13,25):
        empty = run(seq)['workstations'][0]
    assert empty['state'] == 'EMPTY' and empty['checkin']['registered'] is None
    restarted = run(25,generation=1,at=0)['workstations'][0]
    assert restarted['occupied_us'] == empty['occupied_us'] and restarted['checkin']['registered'] is None
    with pytest.raises(ReplayConflict):
        replay.process(detector,b'',ReplayFrame(rid,1,26,.5,1),'person')


@pytest.mark.parametrize('kind', ['duplicate','multiple','unlisted','unknown','marker_only','outside_body'])
def test_uncertain_marker_or_occupancy_cannot_bind_identity(kind):
    zones = [Zone('desk','Meja',tuple(map(tuple,ZONE['polygon'])))]
    checkins = MarkerCheckIns(REGISTRY)
    markers = [marker()]
    state, count = 'OCCUPIED', 1
    if kind == 'duplicate': markers *= 2
    if kind == 'multiple': markers.append(marker(8))
    if kind == 'unlisted': markers = [marker(20)]
    if kind == 'unknown': state, count = 'UNKNOWN', None
    if kind == 'marker_only': state, count = 'EMPTY', 0
    people = [Detection((.1,.1,.9,.9),.95)] if kind != 'outside_body' else [Detection((.1,.1,.3,.3),.95)]
    for at in (0,.5,1):
        rows = checkins.update(markers,[{'zone_id':'desk','state':state,'count':count}],zones,at,people)
    assert rows[0]['checkin']['registered'] is None


def test_moving_checkin_to_another_zone_does_not_duplicate_registration():
    zones=[Zone('a','A',((0,0),(.45,0),(.45,1),(0,1))), Zone('b','B',((.55,0),(1,0),(1,1),(.55,1)))]
    stations=[{'zone_id':z.id,'state':'OCCUPIED','count':1} for z in zones]
    checkins=MarkerCheckIns(REGISTRY)
    people=[Detection((.1,.1,.3,.9),.95),Detection((.7,.1,.9,.9),.95)]
    for at in (0,.5,1):
        rows=checkins.update([marker(center=(.2,.5))],stations,zones,at,people)
    for at in (1.5,2,2.5):
        rows=checkins.update([marker(center=(.8,.5))],stations,zones,at,people)
    assert rows[0]['checkin']['registered'] is None
    assert rows[1]['checkin']['registered']['marker_id'] == 7


@pytest.mark.parametrize('registry', [[{'marker_id':True,'label':'A'}], [{'marker_id':50,'label':'A'}],
    [{'marker_id':7,'label':' '}], [{'marker_id':7.0,'label':'A'}], REGISTRY+REGISTRY])
def test_invalid_registry_does_not_allocate_stream(registry):
    replay=ReplayTracking()
    with pytest.raises(ValueError):
        replay.configure(str(uuid4()),{'expected_revision':0,'zones':[ZONE],'association':'bbox_overlap','markers':registry})
    assert replay.streams == {}
