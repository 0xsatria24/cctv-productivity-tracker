import hashlib
import json
import numpy as np
import pytest

from cctv_tracker.reid.openvino import OpenVinoExtractor
from cctv_tracker.reid.types import AppearanceSample
from reid_helpers import embedding


def model_manifest(tmp_path):
    ov = pytest.importorskip('openvino')
    ops = ov.opset13
    parameter = ops.parameter([1, 3, 16, 8], np.float32)
    mean = ops.reduce_mean(parameter, ops.constant([2, 3], np.int64), False)
    ov.serialize(ov.Model([mean], [parameter]), str(tmp_path/'model.xml'), str(tmp_path/'model.bin'))
    manifest = {'model_id': 'synthetic-contract-only', 'source': 'generated test graph', 'license': 'test fixture',
                'precision': 'f32', 'preprocessing_revision': 'test-v1', 'dimensions': 3,
                'input': {'layout': 'NCHW', 'color': 'RGB', 'height': 16, 'width': 8, 'mean': [0, 0, 0], 'scale': [1, 1, 1]}}
    for key in ('xml', 'bin'):
        path = tmp_path/f'model.{key}'
        manifest[key] = {'path': path.name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    path = tmp_path/'manifest.json'
    path.write_text(json.dumps(manifest))
    return path, manifest


def test_real_openvino_cpu_preprocessing_and_normalized_output(tmp_path):
    path, _ = model_manifest(tmp_path)
    extractor = OpenVinoExtractor(path)
    assert extractor.request is None
    image = np.zeros((32, 16, 3), np.uint8)
    image[:] = [0, 3, 4]
    result = extractor.extract([AppearanceSample(embedding().sample, image)])[0]
    assert result.vector == pytest.approx((.8, .6, 0), abs=1e-4)
    assert result.sample == embedding().sample


def test_tampering_and_tensor_mismatch_are_rejected(tmp_path):
    path, manifest = model_manifest(tmp_path)
    manifest['dimensions'] = 2
    path.write_text(json.dumps(manifest))
    extractor = OpenVinoExtractor(path)
    with pytest.raises(ValueError, match='tensor contract'):
        extractor.extract([AppearanceSample(embedding().sample, np.ones((16, 8, 3), np.uint8))])
    (tmp_path/'model.bin').write_bytes(b'tampered')
    with pytest.raises(ValueError, match='checksum'):
        OpenVinoExtractor(path)
