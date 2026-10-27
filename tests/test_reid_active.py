"""Active application recovery mechanics; synthetic vectors are not field accuracy."""
from dataclasses import replace
from collections import deque
import json
from uuid import uuid4

import pytest

from cctv_tracker.config import Settings, SessionRules
from cctv_tracker.reid.config import ReIdRules
from cctv_tracker.reid.types import EmbeddingResult
from cctv_tracker.replay_tracking import ReplayTracking, ReplayFrame, ReplayConflict
from cctv_tracker.vision import Detection
from reid_helpers import FakeExtractor, MODEL, jpeg
from test_reid_sessions import build, feed


class Detector:
    def __init__(self):
        self.rows = []
    def detect(self, _):
        return {'detections': self.rows, 'inference_ms': 1}


class Appearance(FakeExtractor):
    vector = (1., 0.)
    def extract(self, samples):
        self.calls += 1
        return [EmbeddingResult(sample.ref, MODEL, self.vector) for sample in samples]


def replay_fixture():
    extractor, detector = Appearance(), Detector()
    rules = ReIdRules(mode='active', manifest_path='injected', recovery_policy='short_occlusion',
                       max_extra_latency_ms=60000, sample_interval_seconds=.2, confirm_seconds=.4)
    settings = replace(Settings(), reid=rules, sessions=SessionRules(recovery_confirmation_window_seconds=2))
    replay, replay_id, image = ReplayTracking(settings, reid_extractor=extractor), str(uuid4()), jpeg()
    seq = 0
    def run(at, rows=None, generation=0):
        nonlocal seq
        seq += 1
        detector.rows = rows if rows is not None else [{'box': [.2,.1,.4,.8], 'confidence': .95}]
        return replay.process(detector, image, ReplayFrame(replay_id, generation, seq, at))
    return replay, extractor, run, replay_id


def prime(run):
    packets = [run(at) for at in (0,.4,.8,1.2)]
    assert all(p['reid']['status'] == 'ACTIVE' for p in packets)
    return packets[-1]['detections'][0]['session_id']


def test_stationary_short_occlusion_recovers_session_and_transfers_time_once():
    replay, extractor, run, rid = replay_fixture()
    original = prime(run)
    run(1.4, [])
    provisional = run(1.8)['detections'][0]['session_id']
    assert provisional != original
    pending = run(2.2)
    assert any(s['recovery_pending'] for s in pending['sessions'] if s['session_id'] == provisional)
    packet = run(2.6)
    row = packet['detections'][0]
    assert row['session_id'] == original and row['accumulated_duration_us'] == 2_000_000
    assert packet['reid']['decisions'][0]['action'] == 'MATCH'
    assert packet['session_metrics']['reid_recovered'] == 1
    assert provisional not in replay.streams[rid].reid.gallery.entries
    assert run(3)['detections'][0]['accumulated_duration_us'] == 2_400_000
    assert run(3.4)['session_metrics']['reid_recovered'] == 1


def test_top_clipped_head_is_not_an_exit_but_upward_departure_is_rejected():
    replay, extractor, run, rid = replay_fixture()
    standing = [{'box':[.2,.01,.4,.8],'confidence':.95}]
    for at in (0,.4,.8,1.2):
        packet = run(at,standing)
    old = replay.streams[rid].sessions.sessions[packet['detections'][0]['session_id']]
    run(1.4,[])
    candidate = run(1.8,standing)['detections'][0]['session_id']
    new = replay.streams[rid].sessions.sessions[candidate]
    scorer = replay.streams[rid].reid._short_occlusion_score
    assert scorer(old,new,Detection(tuple(standing[0]['box']),.95),1_800_000_000) is not None
    old.box = (.2,0,.4,.1)
    old.history = deque([(0,(.2,.3,.4,.5)),(600_000_000,(.2,.1,.4,.3)),(1_200_000_000,old.box)])
    new.box = new.origin_box = old.box
    assert scorer(old,new,Detection(old.box,.95),1_800_000_000) is None


def test_different_appearance_cannot_inherit_old_timer():
    replay, extractor, run, rid = replay_fixture()
    original = prime(run)
    run(1.4, [])
    extractor.vector = (0., 1.)
    for at in (1.8,2.2,2.6):
        packet = run(at)
        assert packet['detections'][0]['session_id'] != original
    assert not packet['session_metrics'].get('reid_recovered')
    assert packet['reid']['decisions'][0]['reason'] == 'APPEARANCE_MISMATCH'


def test_same_uniform_two_targets_is_rejected_instead_of_forced_match():
    replay, extractor, run, rid = replay_fixture()
    rows = [{'box': [.1,.1,.25,.8], 'confidence': .95}, {'box': [.35,.1,.5,.8], 'confidence': .95}]
    for at in (0,.4,.8,1.2):
        run(at, rows)
    originals = set(replay.streams[rid].sessions.sessions)
    run(1.4, [])
    middle = [{'box': [.225,.1,.375,.8], 'confidence': .95}]
    for at in (1.8,2.2,2.6):
        packet = run(at,middle)
    assert packet['detections'][0]['session_id'] not in originals
    assert not packet['session_metrics'].get('reid_recovered')


@pytest.mark.parametrize('case', ['exit','far_position','long_gap','seek','bad_crop'])
def test_high_similarity_does_not_bypass_scope_position_time_or_quality(case):
    replay, extractor, run, rid = replay_fixture()
    rows = [{'box':[.005,.1,.205,.8], 'confidence':.95}] if case=='exit' else None
    for at in (0,.4,.8,1.2):
        packet = run(at,rows)
    original = packet['detections'][0]['session_id']
    run(1.4, [])
    if case == 'far_position':
        rows = [{'box':[.65,.1,.85,.8], 'confidence':.95}]
    elif case == 'bad_crop':
        rows = [{'box':[.2,.1,.4,.8], 'confidence':.6}]
    times = (5,5.4,5.8) if case=='long_gap' else (1.8,2.2,2.6)
    for at in times:
        packet = run(at,rows,generation=1 if case=='seek' else 0)
        assert packet['detections'][0]['session_id'] != original
    assert not packet['session_metrics'].get('reid_recovered')


def test_active_motion_pipeline_commits_recovery_and_audit_in_same_checkpoint(tmp_path):
    pipeline, db = build(tmp_path, 'active', FakeExtractor())
    image = jpeg()
    try:
        for seq in range(1,7):
            feed(pipeline,seq,frame_jpeg=image)
        original = next(iter(pipeline.sessions.sessions))
        feed(pipeline,7,rows=[],frame_jpeg=image)
        for seq in (8,9,10):
            packet = feed(pipeline,seq,frame_jpeg=image)
        assert packet['detections'][0]['session_id'] == original
        audit = db.conn.execute("SELECT * FROM reid_decisions WHERE action='MATCH'").fetchone()
        assert audit['target_session_id'] == original
        session = db.conn.execute('SELECT * FROM person_sessions WHERE session_id=?',(original,)).fetchone()
        assert session['updated_event_seq'] == audit['committed_event_seq']
        assert audit['committed_mapping_version'] == packet['mapping_version']
        assert json.loads(audit['model_json'])['model_id'] == MODEL.model_id
    finally:
        pipeline.finish()
        db.close()


def test_failed_recovery_commit_does_not_publish_or_mutate_gallery(tmp_path,monkeypatch):
    pipeline, db = build(tmp_path, 'active', FakeExtractor())
    image = jpeg()
    try:
        for seq in range(1,7):
            feed(pipeline,seq,frame_jpeg=image)
        feed(pipeline,7,rows=[],frame_jpeg=image)
        feed(pipeline,8,frame_jpeg=image)
        feed(pipeline,9,frame_jpeg=image)
        latest, gallery = pipeline.latest, repr(pipeline.reid.gallery.entries)
        before = db.conn.execute('SELECT COUNT(*) FROM reid_decisions').fetchone()[0]
        with db.transaction() as conn:
            conn.execute("CREATE TRIGGER fail_reid BEFORE INSERT ON reid_decisions WHEN NEW.action='MATCH' BEGIN SELECT RAISE(ABORT,'injected reid failure'); END")
        with pytest.raises(Exception,match='injected reid failure'):
            feed(pipeline,10,frame_jpeg=image)
        assert pipeline.latest is latest and repr(pipeline.reid.gallery.entries) == gallery
        assert db.conn.execute('SELECT COUNT(*) FROM reid_decisions').fetchone()[0] == before
    finally:
        pipeline.finish('INTERRUPTED')
        db.close()
