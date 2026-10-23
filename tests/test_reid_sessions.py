from dataclasses import replace
import json
import pytest

from cctv_tracker.config import Settings, SessionRules, Zone, load_settings
from cctv_tracker.persistence import Database
from cctv_tracker.pipeline import Pipeline
from cctv_tracker.reid.config import ReIdRules
from cctv_tracker.vision import Detection
from reid_helpers import FakeExtractor, jpeg


class SuppliedTracks:
    def update(self, rows, *_):
        return rows


def build(tmp_path, mode='shadow', extractor=None):
    rules = ReIdRules(mode=mode, manifest_path='unused-injected-provider', max_extra_latency_ms=60000)
    settings = Settings(database=tmp_path/'test.sqlite3', reid=rules,
                        sessions=SessionRules(recovery_confirm_observations=20),
                        zones=(Zone('desk', 'Desk', ((0, 0), (1, 0), (1, 1), (0, 1))),))
    database = Database(settings.database)
    pipeline = Pipeline(settings, database, 1_000_000, 'SYNTHETIC_REPLAY', 'a'*64, {}, reid_extractor=extractor)
    pipeline.tracker = SuppliedTracks()
    return pipeline, database


def feed(pipeline, seq, at=None, rows=None, **kwargs):
    t = seq*.4 if at is None else at
    if rows is None:
        rows = [Detection((.1+.02*t, .1, .25+.02*t, .8), .95)]
    return pipeline.feed(rows, 1_000_000+int(t*1e6), int(t*1e9), seq, 'g', **kwargs)


def test_shadow_matches_conservatively_without_changing_timers(tmp_path):
    snapshots = []
    for mode in ('off', 'shadow'):
        location = tmp_path/mode
        location.mkdir()
        extractor = FakeExtractor()
        pipeline, database = build(location, mode, extractor)
        frame = jpeg()
        try:
            for seq in range(1, 7):
                feed(pipeline, seq, frame_jpeg=frame)
            original = next(iter(pipeline.sessions.sessions))
            feed(pipeline, 7, rows=[], frame_jpeg=frame)
            reports = [feed(pipeline, seq, frame_jpeg=frame) for seq in range(8, 11)]
            if mode == 'shadow':
                assert reports[-1]['reid']['decisions'][0]['action'] == 'WOULD_MATCH'
                assert reports[-1]['detections'][0]['session_id'] != original
                assert extractor.calls > 0
            else:
                assert extractor.calls == 0
            snapshots.append(([(s.status, s.accumulated_ns, [(k, v.duration_ns) for k, v in s.zones.items()])
                               for s in pipeline.sessions.sessions.values()], dict(pipeline.sessions.metrics)))
        finally:
            pipeline.finish()
            database.close()
    assert snapshots[0] == snapshots[1]


def test_stale_frame_cannot_extract_or_change_gallery(tmp_path):
    extractor = FakeExtractor()
    pipeline, database = build(tmp_path, extractor=extractor)
    try:
        feed(pipeline, 1, frame_jpeg=jpeg())
        before = repr(pipeline.reid.gallery.entries)
        result = feed(pipeline, 1, frame_jpeg=jpeg())
        assert result['ignored'] and extractor.calls == 1
        assert repr(pipeline.reid.gallery.entries) == before
        feed(pipeline, 2, rows=[], unavailable='CAMERA_OFFLINE')
        assert not pipeline.reid.gallery.entries
    finally:
        pipeline.finish()
        database.close()


def test_provider_error_preserves_detector_observation(tmp_path):
    class Broken(FakeExtractor):
        def extract(self, samples):
            raise RuntimeError('test provider failure')
    pipeline, database = build(tmp_path, extractor=Broken())
    try:
        result = feed(pipeline, 1, frame_jpeg=jpeg())
        assert result['detections'] and result['reid']['status'] == 'PROVIDER_ERROR'
        result = feed(pipeline, 2, frame_jpeg=jpeg())
        assert result['detections'] and result['reid']['status'] == 'DISABLED_AFTER_ERROR'
    finally:
        pipeline.finish()
        database.close()


def test_latency_discards_embeddings_and_disables_provider(tmp_path):
    pipeline, database = build(tmp_path, extractor=FakeExtractor())
    pipeline.reid.rules = replace(pipeline.reid.rules, max_extra_latency_ms=.000001)
    try:
        result = feed(pipeline, 1, frame_jpeg=jpeg())
        assert result['reid']['status'] == 'LATENCY_BUDGET'
        assert result['detections'] and not pipeline.reid.gallery.entries
    finally:
        pipeline.finish()
        database.close()


def test_configuration_loads_local_manifest_relative_to_config(tmp_path):
    path = tmp_path/'settings.json'
    path.write_text(json.dumps({'reid': {'mode': 'shadow', 'manifest_path': 'model/manifest.json'}}))
    assert load_settings(path).reid.manifest_path == str((tmp_path/'model/manifest.json').resolve())


def test_competitor_without_embedding_still_vetoes_motion_ambiguity(monkeypatch):
    from types import SimpleNamespace
    from cctv_tracker.reid.runtime import ShadowReId
    from cctv_tracker.reid.types import AppearanceSample
    from cctv_tracker.sessions import SessionManager
    from reid_helpers import embedding, token

    runtime = ShadowReId(ReIdRules(mode='shadow', manifest_path='injected', max_extra_latency_ms=60000), FakeExtractor())
    runtime.gallery.add('old', embedding(1))
    runtime.gallery.add('old', embedding(2))
    query = embedding(3)
    # A competitor's poor crop does not remove its geometric identity risk.
    monkeypatch.setattr('cctv_tracker.reid.runtime.make_crops',
                        lambda *_: ([AppearanceSample(query.sample, None)], [{'detection_index': 1, 'reason': 'CROP_BLURRY'}]))
    old = SimpleNamespace(session_id='old', status='LOST', recoverable=True, generation='gen', last_ns=1_000_000_000)
    first = SimpleNamespace(session_id='first', status='ACTIVE', first_ns=2_000_000_000)
    second = SimpleNamespace(session_id='second', status='ACTIVE', first_ns=2_000_000_000)
    manager = SimpleNamespace(rules=SessionRules(), dirty={}, sessions={'old': old, 'first': first, 'second': second},
                              recovery_score=lambda *_: 1.)
    manager._pairs = lambda *args, **kwargs: SessionManager._pairs(manager, *args, **kwargs)
    detection = Detection((.2, .1, .4, .8), .95)
    stage = runtime.prepare(b'injected', [detection, detection], token(3), manager,
                            [(detection, first), (detection, second)])
    assert stage['report']['status'] == 'SHADOW'
    assert stage['report']['decisions'][0]['reason'] == 'NO_ELIGIBLE_GALLERY'
