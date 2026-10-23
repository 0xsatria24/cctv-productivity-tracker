import math
from typing import Protocol

from .types import AppearanceSample, EmbeddingResult, ModelIdentity


class Extractor(Protocol):
    identity: ModelIdentity

    def extract(self, samples: list[AppearanceSample]) -> list[EmbeddingResult]: ...


def normalize(values, dimensions):
    vector = tuple(float(v) for v in values)
    if len(vector) != dimensions or any(not math.isfinite(v) for v in vector):
        raise ValueError('ReID output has invalid shape or values')
    norm = math.hypot(*vector)
    if norm < 1e-8:
        raise ValueError('ReID output is zero')
    return tuple(v/norm for v in vector)


def validate_batch(results, samples, identity):
    expected = {sample.ref.detection_index: sample.ref for sample in samples}
    seen = set()
    for result in results:
        index = result.sample.detection_index
        if result.model != identity or index in seen or result.sample != expected.get(index):
            raise ValueError('ReID output does not match this measured frame/model')
        # Revalidate even for a provider with a forged or mutated result object.
        EmbeddingResult(result.sample, result.model, result.vector)
        seen.add(index)
    if seen != set(expected):
        raise ValueError('ReID provider omitted requested samples')
