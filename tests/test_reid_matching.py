from dataclasses import replace
import pytest
from cctv_tracker.reid.matcher import Matcher
from cctv_tracker.reid.config import ReIdRules
from reid_helpers import embedding, token


def test_distinct_frames_and_elapsed_confirmation():
    matcher = Matcher(ReIdRules())
    candidates = {'old': [embedding(1), embedding(2)]}
    votes = {}
    for seq in (3, 4, 5):
        decisions, votes = matcher.decide({'new': embedding(seq)}, candidates, token(seq), {('new', 'old')}, votes)
        assert decisions[0].action == ('WOULD_MATCH' if seq == 5 else 'PENDING')
    decisions, duplicate_votes = matcher.decide({'new': embedding(5)}, candidates, token(5), {('new', 'old')}, votes)
    assert decisions[0].action == 'PENDING'


@pytest.mark.parametrize('scenario', ['two_targets', 'two_queries', 'wrong_appearance', 'no_motion', 'expired', 'wrong_model'])
def test_rejection(scenario):
    queries = {'new': embedding(3)}
    candidates = {'old': [embedding(1), embedding(2)]}
    allowed = {('new', 'old')}
    if scenario == 'two_targets':
        candidates['other'] = candidates['old']
        allowed.add(('new', 'other'))
    elif scenario == 'two_queries':
        queries['other'] = embedding(3)
        allowed.add(('other', 'old'))
    elif scenario == 'wrong_appearance':
        queries['new'] = embedding(3, (0., 1.))
    elif scenario == 'no_motion':
        allowed.clear()
    elif scenario == 'expired':
        queries['new'] = embedding(40)
    else:
        e = queries['new']
        queries['new'] = replace(e, model=replace(e.model, preprocessing='different'))
    decisions, votes = Matcher(ReIdRules()).decide(queries, candidates, queries['new'].sample.token, allowed)
    assert all(d.action == 'REJECT' for d in decisions) and not votes


def test_wrong_query_frame_is_rejected():
    with pytest.raises(ValueError):
        Matcher(ReIdRules()).decide({'new': embedding(2)}, {}, token(3), set())


def test_gallery_supports_multiple_views_but_one_outlier_cannot_match():
    matcher = Matcher(ReIdRules())
    samples = [embedding(1),embedding(2),embedding(3,(0.,1.)),embedding(4,(0.,1.))]
    decisions,_ = matcher.decide({'new':embedding(5)}, {'old':samples},token(5),{('new','old')})
    assert decisions[0].action == 'PENDING' and decisions[0].score == 1
    samples[1] = embedding(2,(0.,1.))
    decisions,_ = matcher.decide({'new':embedding(5)}, {'old':samples},token(5),{('new','old')})
    assert decisions[0].reason == 'APPEARANCE_MISMATCH'
