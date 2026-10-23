from dataclasses import replace
import cv2
import numpy as np

from cctv_tracker.reid.types import FrameToken, ModelIdentity, SampleRef, EmbeddingResult

MODEL = ModelIdentity('test-only', 'a'*64, 'test-v1', 2)


def token(seq=1, at=None, **changes):
    return replace(FrameToken('cam', 'run', 'gen', seq, int((seq if at is None else at)*1e9), 0), **changes)


def embedding(seq=1, vector=(1., 0.), **changes):
    return EmbeddingResult(SampleRef(token(seq, **changes), 0, (.2, .1, .4, .8), 100., .95), MODEL, vector)


def jpeg():
    image = np.random.default_rng(42).integers(0, 255, (360, 640, 3), dtype=np.uint8)
    return cv2.imencode('.jpg', image)[1].tobytes()


class FakeExtractor:
    identity = MODEL

    def __init__(self):
        self.calls = 0

    def extract(self, samples):
        self.calls += 1
        return [EmbeddingResult(sample.ref, MODEL, (1., 0.)) for sample in samples]
