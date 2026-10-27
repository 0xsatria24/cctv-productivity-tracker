from dataclasses import replace
import cv2
import numpy as np
import pytest
from cctv_tracker.reid.config import ReIdRules
from cctv_tracker.reid.crops import make_crops
from cctv_tracker.vision import Detection
from reid_helpers import jpeg, token


def test_original_frame_crop_and_overlap_veto():
    rows = [Detection((.2, .1, .4, .8), .95)]
    samples, rejected = make_crops(jpeg(), rows, token(), ReIdRules())
    assert not rejected
    assert samples[0].image.shape == (252, 128, 3)
    assert samples[0].ref.token == token()
    samples, rejected = make_crops(jpeg(), rows*2, token(), ReIdRules())
    assert not samples and {r['reason'] for r in rejected} == {'CROWD_OVERLAP'}


@pytest.mark.parametrize('box,confidence,reason', [
    ((0, .1, .2, .8), .95, 'FRAME_EDGE'),
    ((.2, .1, .21, .2), .95, 'CROP_TOO_SMALL'),
    ((.2, .1, .4, .8), .4, 'LOW_CONFIDENCE'),
    ((.1, .1, .8, .5), .95, 'PARTIAL_BODY_SHAPE')])
def test_quality_veto(box, confidence, reason):
    samples, rejected = make_crops(jpeg(), [Detection(box, confidence)], token(), ReIdRules())
    assert not samples and rejected[0]['reason'] == reason


def test_blur_corrupt_input_and_budget():
    flat = cv2.imencode('.jpg', np.zeros((360, 640, 3), np.uint8))[1].tobytes()
    rows = [Detection((.1, .1, .25, .8), .95), Detection((.5, .1, .65, .8), .95)]
    assert make_crops(flat, rows, token(), ReIdRules())[1][0]['reason'] == 'CROP_BLURRY'
    samples, rejected = make_crops(jpeg(), rows, token(), replace(ReIdRules(), max_crops_per_frame=1))
    assert len(samples) == 1 and rejected[0]['reason'] == 'CROP_BUDGET'
    with pytest.raises(ValueError):
        make_crops(b'broken', rows, token(), ReIdRules())
