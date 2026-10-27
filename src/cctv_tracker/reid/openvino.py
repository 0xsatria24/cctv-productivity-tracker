"""Pinned local IR provider. Importing this module does not load OpenVINO."""
import hashlib
import json
import math
from pathlib import Path
import threading

from .extractor import normalize
from .types import EmbeddingResult, ModelIdentity


class OpenVinoExtractor:
    def __init__(self, manifest_path, *, device='CPU'):
        if device not in {'CPU', 'GPU'}:
            raise ValueError('Unsupported ReID device')
        path = Path(manifest_path).resolve()
        manifest = json.loads(path.read_text(encoding='utf-8'))
        self.device, self.lock = device, threading.Lock()
        for key in ('model_id', 'source', 'license', 'precision', 'preprocessing_revision'):
            if not isinstance(manifest.get(key), str) or not manifest[key].strip():
                raise ValueError(f'Missing ReID manifest {key}')
        self.files = []
        hashes = []
        for key, suffix in (('xml', '.xml'), ('bin', '.bin')):
            item = manifest[key]
            artifact = (path.parent / item['path']).resolve()
            if not artifact.is_relative_to(path.parent) or artifact.suffix != suffix:
                raise ValueError('ReID artifact must be inside the manifest directory')
            digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
            if digest != item['sha256']:
                raise ValueError(f'ReID {key} checksum mismatch')
            self.files.append(artifact)
            hashes.append(digest)
        spec = manifest['input']
        if spec.get('layout') != 'NCHW' or spec.get('color') not in {'BGR', 'RGB'}:
            raise ValueError('ReID requires NCHW and explicit BGR/RGB input')
        if any(type(spec.get(k)) is not int or not 8 <= spec[k] <= 1024 for k in ('height', 'width')):
            raise ValueError('Invalid ReID input size')
        for key in ('mean', 'scale'):
            values = spec.get(key)
            if not isinstance(values, list) or len(values) != 3 or any(type(v) not in (int, float) or not math.isfinite(v) for v in values):
                raise ValueError(f'Invalid ReID input {key}')
        if any(v <= 0 for v in spec['scale']):
            raise ValueError('ReID scale must be positive')
        self.spec = spec
        preprocessing = manifest['preprocessing_revision'] + ':' + hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()
        self.identity = ModelIdentity(manifest['model_id'], hashlib.sha256(''.join(hashes).encode()).hexdigest(),
                                      preprocessing, manifest['dimensions'])
        self.manifest = manifest
        self.compiled = self.request = None

    def _load(self):
        import openvino as ov
        core = ov.Core()
        if self.device not in {d.split('.')[0] for d in core.available_devices}:
            raise RuntimeError(f'OpenVINO ReID {self.device} unavailable')
        model = core.read_model(str(self.files[0]), str(self.files[1]))
        expected = [1, 3, self.spec['height'], self.spec['width']]
        if (len(model.inputs) != 1 or list(model.input(0).shape) != expected or len(model.outputs) != 1
                or list(model.output(0).shape) not in ([1, self.identity.dimensions], [1, self.identity.dimensions, 1, 1])):
            raise ValueError('ReID model tensor contract mismatch')
        compiled = core.compile_model(model, self.device, {'PERFORMANCE_HINT': 'LATENCY', 'NUM_STREAMS': '1'})
        devices = compiled.get_property('EXECUTION_DEVICES')
        if not devices or any(d.split('.')[0] != self.device for d in devices):
            raise RuntimeError('ReID execution device mismatch')
        self.compiled, self.request = compiled, compiled.create_infer_request()

    def warmup(self):
        with self.lock:
            if self.request is not None:
                return False
            self._load()
            return True

    def extract(self, samples):
        import cv2
        import numpy as np
        if not samples:
            return []
        with self.lock:
            if self.request is None:
                self._load()
            results = []
            for sample in samples:
                image = cv2.resize(sample.image, (self.spec['width'], self.spec['height']), interpolation=cv2.INTER_LINEAR)
                if self.spec['color'] == 'RGB':
                    image = image[:, :, ::-1]
                image = (image.astype(np.float32) - np.asarray(self.spec['mean'], dtype=np.float32)) * np.asarray(self.spec['scale'], dtype=np.float32)
                blob = np.ascontiguousarray(image.transpose(2, 0, 1)[None])
                self.request.infer({self.compiled.input(0): blob})
                vector = normalize(self.request.get_output_tensor(0).data.reshape(-1), self.identity.dimensions)
                results.append(EmbeddingResult(sample.ref, self.identity, vector))
            return results
