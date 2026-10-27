from uuid import uuid4
import json

import pytest

from cctv_tracker.replay_tracking import ReplayFrame, ReplayTracking
from test_aruco_workstation import Detector, ZONE


def setup(tmp_path=None):
    replay=ReplayTracking(state_dir=tmp_path)
    rid=str(uuid4())
    config={'expected_revision':0,'zones':[ZONE],'association':'bbox_overlap','markers':[]}
    replay.configure(rid,config)
    detector=Detector()
    sequence=0
    def run(at,generation=0,revision=1):
        nonlocal sequence
        sequence+=1
        return replay.process(detector,b'',ReplayFrame(rid,generation,sequence,at,revision),'workstation')
    return replay,rid,config,run


def test_seek_and_loop_preserve_totals_without_recounting_or_charging_skipped_video():
    replay,rid,config,run=setup()
    for i in range(11):
        first=run(i*.5)['workstations'][0]
    assert first['occupied_us']==3_000_000 and first['observed_us']==5_000_000
    for i in range(11):
        replayed=run(i*.5,1)['workstations'][0]
        assert replayed['occupied_us']==first['occupied_us']
        assert replayed['observed_us']==first['observed_us']
    extended=run(5.5,1)['workstations'][0]
    assert extended['occupied_us']==3_500_000
    jumped=run(100,2)['workstations'][0]
    assert jumped['observed_us']==extended['observed_us']
    assert run(100.5,2)['workstations'][0]['observed_us']==extended['observed_us']+500_000


def test_position_intervals_survive_seek_and_do_not_bridge_skipped_media():
    replay,rid,config,run=setup()
    for i in range(11): first=run(i*.5)['workstations'][0]
    assert first['media_intervals']==[[0,2_000_000,'UNKNOWN'],[2_000_000,5_000_000,'OCCUPIED']]
    for i in range(11): repeated=run(i*.5,1)['workstations'][0]
    assert repeated['media_intervals']==first['media_intervals']
    run(100,2)
    jumped=run(100.5,2)['workstations'][0]
    assert jumped['media_intervals']==first['media_intervals']+[[100_000_000,100_500_000,'UNKNOWN']]
    assert jumped['media_intervals_complete']
    clock=replay.streams[rid].area_workstations.clocks[ZONE['id']]
    clock.remember(1_000_000,4_000_000,'EMPTY')
    assert clock.snapshot(replay.streams[rid].settings.zones[0])['media_intervals']==jumped['media_intervals']


def test_noop_and_rename_preserve_results_but_shape_edits_archive_only_changed_area():
    replay,rid,config,run=setup()
    for i in range(11): packet=run(i*.5)
    first=packet['workstations'][0]
    unchanged=replay.configure(rid,{**config,'expected_revision':1})
    assert not unchanged['changed'] and unchanged['calibration_revision']==1
    assert unchanged['workstations'][0]['occupied_us']==first['occupied_us']
    renamed={**ZONE,'name':'Nama baru'}
    result=replay.configure(rid,{**config,'expected_revision':1,'zones':[renamed]})
    assert result['workstations'][0]['occupied_us']==first['occupied_us']
    assert result['workstation_history']==[]
    changed={**renamed,'polygon':[[.1,.1],[.8,.1],[.8,.8],[.1,.8]]}
    result=replay.configure(rid,{**config,'expected_revision':2,'zones':[changed]})
    assert result['workstations']==[]
    assert result['workstation_history'][0]['occupied_us']==first['occupied_us']
    assert run(6,1,3)['workstations'][0]['occupied_us']==0


def test_checkpoint_restores_calibration_and_unique_totals_after_engine_restart(tmp_path):
    replay,rid,config,run=setup(tmp_path)
    for i in range(11): first=run(i*.5)['workstations'][0]
    assert replay.checkpoint(rid)['saved']
    restored=ReplayTracking(state_dir=tmp_path)
    saved=restored.calibration(rid)
    assert saved['zones'][0]['name']==ZONE['name']
    assert saved['workstations'][0]['occupied_us']==first['occupied_us']
    assert saved['workstations'][0]['media_intervals']==first['media_intervals']
    for i in range(11):
        packet=restored.process(Detector(),b'',ReplayFrame(rid,0,i+1,i*.5,1),'workstation')
    assert packet['workstations'][0]['observed_us']==first['observed_us']
    restored.checkpoint(rid)
    record=json.loads((tmp_path/(rid+'.json')).read_text())
    assert record['workstations']['clocks'][ZONE['id']]['covered']==[[0,5_000_000]]


def test_legacy_checkpoint_keeps_totals_and_builds_position_details_on_replay(tmp_path):
    replay,rid,config,run=setup(tmp_path)
    for i in range(11): first=run(i*.5)['workstations'][0]
    replay.checkpoint(rid)
    path=tmp_path/(rid+'.json')
    record=json.loads(path.read_text())
    del record['workstations']['clocks'][ZONE['id']]['media_intervals']
    path.write_text(json.dumps(record))
    restored=ReplayTracking(state_dir=tmp_path)
    legacy=restored.calibration(rid)['workstations'][0]
    assert legacy['occupied_us']==first['occupied_us']
    assert legacy['media_intervals']==[] and not legacy['media_intervals_complete']
    for i in range(11):
        packet=restored.process(Detector(),b'',ReplayFrame(rid,0,i+1,i*.5,1),'workstation')
    row=packet['workstations'][0]
    assert row['occupied_us']==first['occupied_us'] and row['observed_us']==first['observed_us']
    assert row['media_intervals']==first['media_intervals'] and row['media_intervals_complete']


@pytest.mark.parametrize('intervals',[
    [[0,6_000_000,'OCCUPIED']],[[0,1_000_000,'INVALID']],
    [[0,3_000_000,'OCCUPIED'],[2_000_000,4_000_000,'EMPTY']],[[1,0,'UNKNOWN']],
])
def test_invalid_position_intervals_cannot_restore_as_measurements(tmp_path,intervals):
    replay,rid,config,run=setup(tmp_path)
    for i in range(11): run(i*.5)
    replay.checkpoint(rid)
    path=tmp_path/(rid+'.json')
    record=json.loads(path.read_text())
    record['workstations']['clocks'][ZONE['id']]['media_intervals']=intervals
    path.write_text(json.dumps(record))
    with pytest.raises(ValueError,match='[Ii]nterval|[Cc]overage'):
        ReplayTracking(state_dir=tmp_path).calibration(rid)


def test_corrupt_checkpoint_is_rejected_instead_of_replacing_it_with_zero(tmp_path):
    replay,rid,config,run=setup(tmp_path)
    for i in range(11): run(i*.5)
    replay.checkpoint(rid)
    path=tmp_path/(rid+'.json')
    saved=json.loads(path.read_text())
    saved['workstations']['clocks'][ZONE['id']]['totals']['OCCUPIED']+=1
    path.write_text(json.dumps(saved))
    with pytest.raises(ValueError,match='coverage'):
        ReplayTracking(state_dir=tmp_path).calibration(rid)
    assert json.loads(path.read_text())==saved


def test_checkpoint_disk_failure_does_not_discard_live_area_totals(tmp_path,monkeypatch):
    replay,rid,config,run=setup(tmp_path)
    for i in range(11): first=run(i*.5)['workstations'][0]
    def fail(*args): raise OSError('disk full')
    monkeypatch.setattr(replay.store,'write',fail)
    assert not replay.checkpoint(rid)['saved']
    packet=run(5.5)
    assert packet['workstations'][0]['occupied_us']>first['occupied_us']
    assert packet['save_error']
