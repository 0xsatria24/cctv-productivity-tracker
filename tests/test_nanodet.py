import cv2
import numpy as np
import pytest
from cctv_tracker.nanodet import NanoDetDetector, NANO_PATH
from cctv_tracker.vision import Detection


def test_nanodet_hash_failure_before_model_load(tmp_path):
    path = tmp_path / 'bad.onnx'
    path.write_bytes(b'not the licensed model')
    detector = NanoDetDetector(path)
    with pytest.raises(RuntimeError, match='Checksum'):
        detector.detect(b'irrelevant')


@pytest.mark.skipif(not NANO_PATH.exists(), reason='Install optional NanoDet model')
def test_actual_nanodet_zero_detections_on_landscape_portrait_and_square_frames():
    detector = NanoDetDetector()
    for w, h in ((640, 360), (240, 480), (320, 320)):
        result = detector.detect(cv2.imencode('.jpg', np.zeros((h, w, 3), np.uint8))[1].tobytes())
        assert result['count'] == 0
        assert (result['width'], result['height']) == (w, h)
        assert result['model'] == 'NanoDet · CPU'
        assert result['inference_ms'] > 0
    assert detector.session.get_providers() == ['CPUExecutionProvider']


@pytest.mark.skipif(not (NANO_PATH.parent / 'person-test.png').exists(), reason='Optional official OpenCV smoke-test image')
def test_actual_nanodet_person_sample_is_normalized():
    detector = NanoDetDetector()
    image = cv2.imread(str(NANO_PATH.parent / 'person-test.png'))
    result = detector.detect(cv2.imencode('.jpg', image)[1].tobytes())
    assert result['count'] == 2
    for row in result['detections']:
        Detection(tuple(row['box']), row['confidence'])
