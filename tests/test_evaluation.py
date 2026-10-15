import pytest
from cctv_tracker.evaluation import evaluate


def truth():
    return {'version': 1, 'zones': [{'id': 'desk', 'name': 'Desk', 'polygon': [[0, 0], [1, 0], [1, 1], [0, 1]],
             'intervals': [{'start_seconds': 0, 'end_seconds': 10, 'state': 'OCCUPIED'}, {'start_seconds': 10, 'end_seconds': 20, 'state': 'EMPTY'}]}]}


def test_accuracy_cannot_hide_unknown_and_missing_classes():
    predictions = {'desk': [{'start_seconds': 0, 'end_seconds': 1, 'state': 'OCCUPIED'}, {'start_seconds': 10, 'end_seconds': 11, 'state': 'EMPTY'}]}
    result = evaluate(truth(), predictions, .8)
    assert result['coverage'] == .1
    assert result['unknown_seconds'] == 18
    assert result['classes']['OCCUPIED']['precision_valid'] == 1
    assert not result['gate']['passed']
    assert evaluate(truth(), {'desk': truth()['zones'][0]['intervals']}, .8)['gate']['passed']
    assert not evaluate(truth(), {}, .8)['gate']['passed']


def test_duration_weighting_and_overlap_rejection():
    rows = [{'start_seconds': 0, 'end_seconds': 5, 'state': 'EMPTY'}, {'start_seconds': 5, 'end_seconds': 20, 'state': 'OCCUPIED'}]
    result = evaluate(truth(), {'desk': rows}, .8)
    assert result['classes']['OCCUPIED']['precision_valid'] == 1 / 3
    assert result['classes']['OCCUPIED']['recall_valid'] == .5
    rows[1]['start_seconds'] = 4
    with pytest.raises(ValueError, match='overlap'):
        evaluate(truth(), {'desk': rows}, .8)
