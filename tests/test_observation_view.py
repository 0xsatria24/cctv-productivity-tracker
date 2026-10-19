from cctv_tracker.observation_view import observation_view


def packet(captured, published, observation=None):
    return {'monotonic_ns': int(captured * 1e9), 'published_monotonic_ns': int(published * 1e9),
            'utc_ms': 123, 'sequence': 4, 'observation': observation or {'detections': [], 'count': 0}}


def test_slow_completed_result_is_visible_without_fabricating_zero_detections():
    measured = {'count': 1, 'detections': [{'box': [.1, .1, .4, .8], 'track_id': 'a:1'}]}
    result = observation_view(packet(10, 10.8, measured), int(10.9e9))
    assert result['observation'] is measured
    assert result['valid_for_ms'] == 1400
    assert result['source_age_ms'] == 900
    assert result['result_age_ms'] == 100


def test_expired_overlay_offline_and_actual_empty_result_clear_boxes():
    assert observation_view(None, 10)['observation'] is None
    assert observation_view(packet(10, 10.1), int(11.7e9))['valid_for_ms'] == 0
    assert observation_view(packet(10, 12.8), int(13.1e9))['observation'] is None
    pair = packet(10, 10.1)
    assert observation_view(pair, int(10.2e9))['observation']['detections'] == []
    pair['observation'] = None  # Engine cleared latest after an accounting/transport gap.
    assert observation_view(pair, int(10.2e9))['valid_for_ms'] == 0
