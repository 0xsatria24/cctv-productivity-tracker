import pytest
from test_reid_sessions import build, feed
from reid_helpers import FakeExtractor, jpeg


def test_gallery_votes_and_publication_wait_for_database_commit(tmp_path, monkeypatch):
    pipeline, database = build(tmp_path, extractor=FakeExtractor())
    try:
        feed(pipeline, 1, frame_jpeg=jpeg())
        before = repr(pipeline.reid.gallery.entries)
        latest = pipeline.latest
        def fail(*args, **kwargs):
            raise RuntimeError('injected commit failure')
        with monkeypatch.context() as patch:
            patch.setattr(pipeline.writer, 'commit', fail)
            with pytest.raises(RuntimeError, match='injected'):
                feed(pipeline, 2, frame_jpeg=jpeg())
        assert pipeline.latest is latest
        assert repr(pipeline.reid.gallery.entries) == before
        assert pipeline.reid.last_sample_ns == 400_000_000
    finally:
        pipeline.finish('INTERRUPTED')
        database.close()
