from dataclasses import replace
import math
import pytest
from cctv_tracker.reid.extractor import normalize, validate_batch
from cctv_tracker.reid.types import AppearanceSample, EmbeddingResult, SampleRef
from cctv_tracker.reid.config import ReIdRules
from reid_helpers import MODEL, embedding


@pytest.mark.parametrize('values', [(0, 0), (math.nan, 1), (math.inf, 0), (1, 2, 3)])
def test_bad_vectors(values):
    with pytest.raises(ValueError):
        normalize(values, 2)


def test_normalization_and_exact_frame_contract():
    assert normalize((3, 4), 2) == (.6, .8)
    result = embedding()
    samples = [AppearanceSample(result.sample, None)]
    validate_batch([result], samples, MODEL)
    for results in ([], [result, result], [embedding(2)], [replace(result, model=replace(MODEL, preprocessing='different'))]):
        with pytest.raises(ValueError):
            validate_batch(results, samples, MODEL)
    with pytest.raises(ValueError):
        EmbeddingResult(result.sample, MODEL, (2., 0.))
    with pytest.raises(ValueError):
        replace(result.sample, box=(0, 0, 0, 1))


@pytest.mark.parametrize('changes', [{'mode': 'active'}, {'mode': 'shadow'}, {'confirm_observations': True},
    {'min_similarity': float('nan')}, {'min_gallery_samples': 5}, {'max_gap_seconds': 40}, {'device': 'AUTO'}])
def test_rules_reject_unsupported_settings(changes):
    with pytest.raises(ValueError):
        ReIdRules(**changes)
