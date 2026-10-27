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


@pytest.mark.parametrize('bad', [float('nan'),float('inf'),-1])
def test_nonfinite_and_negative_predictions_are_rejected(bad):
    with pytest.raises(ValueError):
        evaluate(truth(),{'desk':[{'start_seconds':bad,'end_seconds':20,'state':'EMPTY'}]},.8)


def test_replay_uses_weak_candidates_and_live_image_transform(tmp_path,monkeypatch):
    import json
    from types import SimpleNamespace
    import cctv_tracker.engine as engine
    from cctv_tracker.evaluation import replay_video
    from test_dataset import make_video
    video=tmp_path/'source.mp4';make_video(video)
    annotation=truth()
    annotation['zones'][0]['intervals']=[{'start_seconds':0,'end_seconds':1.1,'state':'OCCUPIED'}]
    path=tmp_path/'labels.json';path.write_text(json.dumps(annotation))
    def detect(jpeg):
        import cv2
        import numpy as np
        assert cv2.imdecode(np.frombuffer(jpeg,np.uint8),1).shape[:2] == (320,640)
        return {'detections':[],'tracking_candidates':[{'box':[.1,.1,.4,.8],'confidence':.2}]}
    fake=SimpleNamespace(detect=detect,sha='f'*64,manifest={'source':'SYNTHETIC_TEST'})
    monkeypatch.setattr(engine,'create_detector',lambda *_:fake)
    result=replay_video(video,path,tmp_path/'evaluation',minimum_coverage=.8)
    assert result['coverage'] == 0  # Weak person evidence is UNKNOWN, not EMPTY.
    assert result['corrupt_frames_dropped'] == 0
    assert result['wall_clock_capacity_validated'] is False
    predictions=json.loads((tmp_path/'evaluation'/'predictions.json').read_text())
    assert {r['state'] for r in predictions['desk']} == {'UNKNOWN'}
