from uuid import uuid4

import pytest

from cctv_tracker.replay_tracking import ReplayConflict, ReplayFrame, ReplayTracking


ZONE = {'id': 'desk-1', 'name': 'Meja potong', 'polygon': [[.1,.1],[.9,.1],[.9,.9],[.1,.9]]}


class Detector:
    rows = [{'box': [.3,.2,.5,.8], 'confidence': .95}]
    calls = 0

    def detect(self, _):
        self.calls += 1
        return {'detections': self.rows, 'inference_ms': 1}


def fixture():
    replay, detector, replay_id = ReplayTracking(), Detector(), str(uuid4())
    result = replay.configure(replay_id, {'expected_revision': 0, 'zones': [ZONE], 'association': 'bbox_overlap'})
    assert result['calibration_revision'] == 1 and not result['duration_accounting']
    return replay, detector, replay_id


def feed(replay, detector, replay_id, at, seq, generation=0, revision=1):
    return replay.process(detector, b'', ReplayFrame(replay_id, generation, seq, at, revision))


def test_workstation_total_survives_person_replacement_and_never_charges_missing_gap():
    replay, detector, rid = fixture()
    for seq in range(1,22):
        packet = feed(replay,detector,rid,(seq-1)*.2,seq)
    original = packet['detections'][0]['session_id']
    clock = packet['workstations'][0]
    assert clock['state'] == 'OCCUPIED' and clock['occupied_us'] == 2_000_000
    detector.rows = []
    lost = feed(replay,detector,rid,4.2,22)['workstations'][0]
    assert lost['state'] == 'UNKNOWN' and lost['occupied_us'] == clock['occupied_us']
    detector.rows = Detector.rows
    for seq in range(23,45):
        packet = feed(replay,detector,rid,(seq-1)*.2,seq)
    assert packet['detections'][0]['session_id'] != original
    clock = packet['workstations'][0]
    assert clock['occupied_us'] > 2_000_000
    assert clock['occupied_us'] + clock['empty_us'] + clock['unknown_us'] == clock['observed_us'] == 8_600_000
    assert not packet['duration_accounting'] and not packet['recorded']
    assert len(replay.streams[rid].workstations.clocks['desk-1'].accumulator.closed) == 0


def test_frame_gap_weak_evidence_and_ambiguous_zones_freeze_occupied_total():
    replay, detector, rid = fixture()
    for seq in range(1,22):
        packet = feed(replay,detector,rid,(seq-1)*.2,seq)
    occupied = packet['workstations'][0]['occupied_us']
    detector.rows = [{'box': [.3,.2,.5,.8], 'confidence': .47}]
    weak = feed(replay,detector,rid,4.2,22)['workstations'][0]
    assert weak['state'] == 'UNKNOWN' and weak['occupied_us'] == occupied
    detector.rows = Detector.rows
    gap = feed(replay,detector,rid,12,23)['workstations'][0]
    assert gap['state'] == 'UNKNOWN' and gap['occupied_us'] == occupied
    assert gap['unknown_us'] >= 8_000_000
    replay.configure(rid, {'expected_revision':1, 'zones':[ZONE,{**ZONE,'id':'desk-2'}], 'association':'bbox_overlap'})
    packet = feed(replay,detector,rid,12.2,24,generation=1,revision=2)
    assert all(z['state']=='UNKNOWN' and z['reason']=='ZONE_AMBIGUOUS' for z in packet['workstations'])


def test_seek_calibration_and_stale_revision_cannot_reuse_or_corrupt_totals():
    replay, detector, rid = fixture()
    for seq in range(1,22):
        feed(replay,detector,rid,(seq-1)*.2,seq)
    calls=detector.calls
    with pytest.raises(ReplayConflict):
        feed(replay,detector,rid,4.2,22,revision=0)
    assert detector.calls == calls
    assert replay.streams[rid].workstations.clocks['desk-1'].totals['OCCUPIED'] == 2_000_000
    restarted=feed(replay,detector,rid,1,22,generation=1)['workstations'][0]
    assert restarted['occupied_us']==0 and restarted['observed_us']==0
    calibration=replay.configure(rid, {'expected_revision':1,'zones':[ZONE],'association':'footpoint'})
    assert calibration['minimum_sequence']==23 and calibration['minimum_generation']==2
    with pytest.raises(ReplayConflict):
        feed(replay,detector,rid,1.2,23,generation=1,revision=2)
    packet=feed(replay,detector,rid,1.2,23,generation=2,revision=2)
    assert packet['workstations'][0]['occupied_us']==0
    with pytest.raises(ReplayConflict):
        replay.configure(rid, {'expected_revision':1,'zones':[],'association':'footpoint'})
    assert replay.calibration(rid)['calibration_revision']==2


def test_empty_requires_confirmation_and_tracks_separately_from_unknown():
    replay, detector, rid = fixture()
    detector.rows=[]
    for seq in range(1,32):
        packet=feed(replay,detector,rid,(seq-1)*.2,seq)
    clock=packet['workstations'][0]
    assert clock['state']=='EMPTY' and clock['occupied_us']==0
    assert clock['empty_us']==1_000_000 and clock['unknown_us']==5_000_000


@pytest.mark.parametrize('change', [
    {'zones':[ZONE,ZONE]}, {'zones':[{**ZONE,'polygon':[[0,0],[1,1],[0,1],[1,0]]}]},
    {'zones':[{**ZONE,'polygon':[[0,0],[True,1],[0,1]]}]},
    {'zones':[{**ZONE,'polygon':[[0,0],[float('nan'),1],[0,1]]}]},
    {'zones':[{**ZONE,'name':' '}]}, {'zones':[ZONE]*17},
    {'association':'homography'}, {'expected_revision':True}, {'extra':0},
])
def test_invalid_calibration_rejected_before_allocating_stream(change):
    replay, rid=ReplayTracking(),str(uuid4())
    with pytest.raises(ValueError):
        replay.configure(rid, {'expected_revision':0,'zones':[ZONE],'association':'bbox_overlap',**change})
    assert replay.streams=={}


def test_long_workstation_timeline_has_bounded_memory_and_no_person_multiplier():
    from dataclasses import replace
    from cctv_tracker.config import Settings, Zone
    from cctv_tracker.workstations import WorkstationTimeline
    from cctv_tracker.vision import Detection
    settings=replace(Settings(), zones=(Zone('desk','Meja',tuple(map(tuple,ZONE['polygon']))),))
    timeline=WorkstationTimeline(settings)
    for seq in range(1,10002):
        rows=timeline.update([Detection((.3,.2,.5,.8),.95)]*(1+seq%3),ReplayFrame('test',0,seq,(seq-1)*.2))
    assert rows[0]['observed_us']==2_000_000_000
    assert rows[0]['occupied_us']==1_998_000_000
    assert timeline.clocks['desk'].accumulator.closed==[]


def test_clipped_feet_are_unknown_in_footpoint_mode():
    replay, detector, rid=fixture()
    replay.configure(rid, {'expected_revision':1,'zones':[ZONE],'association':'footpoint'})
    detector.rows=[{'box':[.3,.2,.5,1], 'confidence':.95}]
    packet=feed(replay,detector,rid,0,1,revision=2)
    assert packet['workstations'][0]['state']=='UNKNOWN'


def test_failed_tracker_cannot_advance_workstation_time(monkeypatch):
    replay, detector, rid=fixture()
    feed(replay,detector,rid,0,1)
    stream=replay.streams[rid]
    def fail(*args):
        raise RuntimeError('tracker unavailable')
    with monkeypatch.context() as patch:
        patch.setattr(stream.tracker,'update',fail)
        with pytest.raises(RuntimeError):
            feed(replay,detector,rid,.2,2)
    assert stream.workstations.clocks['desk-1'].accumulator.last.frame_seq==1
    assert feed(replay,detector,rid,.2,2)['workstations'][0]['observed_us']==200_000
