"""Freshness of measured overlays, independent of video refresh and accounting."""


def observation_view(pair, now_ns):
    if not pair:
        return {'observation': None, 'sequence': 0, 'utc_ms': None, 'valid_for_ms': 0}
    source_age = max(0, (now_ns - pair['monotonic_ns']) / 1e6)
    result_age = max(0, (now_ns - pair.get('published_monotonic_ns', pair['monotonic_ns'])) / 1e6)
    # A completed inference can already be older than 500ms at publication.
    # Bound both camera evidence age and time since the last completed result.
    remaining = max(0, min(3000 - source_age, 1500 - result_age))
    observation = pair.get('observation') if remaining > 0 else None
    return {'observation': observation, 'sequence': pair['sequence'], 'utc_ms': pair['utc_ms'],
            'source_age_ms': round(source_age), 'result_age_ms': round(result_age),
            'valid_for_ms': round(remaining) if observation is not None else 0}
