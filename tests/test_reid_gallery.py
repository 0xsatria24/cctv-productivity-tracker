from dataclasses import replace
import pytest
from cctv_tracker.reid.config import ReIdRules
from cctv_tracker.reid.gallery import Gallery
from reid_helpers import MODEL, embedding, token


def test_bounded_samples_sessions_and_independent_frames():
    gallery = Gallery(replace(ReIdRules(), max_gallery_sessions=1, max_gallery_samples=2))
    assert gallery.add('a', embedding())
    assert not gallery.add('a', embedding())
    gallery.add('a', embedding(2))
    gallery.add('a', embedding(3))
    assert len(gallery.entries['a']) == 2
    assert gallery.samples('a', token(4), MODEL)
    assert not gallery.samples('a', token(4, generation_id='other'), MODEL)
    assert not gallery.samples('a', token(4), replace(MODEL, preprocessing='other'))
    with pytest.raises(ValueError):
        gallery.add('a', embedding(4, generation_id='other'))
    gallery.add('b', embedding(4))
    assert set(gallery.entries) == {'b'}
    gallery.prune(token(40), {'b'})
    assert not gallery.entries


def test_reconnect_or_expiration_discards_gallery():
    gallery = Gallery(ReIdRules())
    gallery.add('a', embedding())
    gallery.prune(token(2, generation_id='reconnect'), {'a'})
    assert not gallery.entries
    gallery.add('a', embedding(3))
    gallery.prune(token(4), set())
    assert not gallery.entries


def test_committed_reconciliation_moves_samples_once():
    gallery = Gallery(ReIdRules())
    gallery.add('old', embedding(1))
    gallery.add('temporary', embedding(2))
    gallery.add('temporary', embedding(3))
    gallery.reconcile('temporary', 'old')
    assert 'temporary' not in gallery.entries
    assert len(gallery.entries['old']) == 3
    gallery.reconcile('temporary', 'old')
    assert len(gallery.entries['old']) == 3
