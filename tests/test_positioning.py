"""Geometry and accounting fixtures; no camera accuracy claim."""
from dataclasses import asdict, replace
import json

import pytest

from cctv_tracker.config import Settings, Rules, Zone, load_settings
from cctv_tracker.domain.occupancy import State
from cctv_tracker.live import validate_calibration, LiveController
from cctv_tracker.persistence import Database
from cctv_tracker.pipeline import Pipeline
from cctv_tracker.positioning import PositionCalibration, measured_position, project
from cctv_tracker.vision import Detection, associate


QUAD = ((0.2, 0.1), (0.8, 0.1), (1., 0.9), (0., 0.9))
ZONES = (Zone('left', 'Left', ((0, 0), (0.5, 0), (0.5, 1), (0, 1))),
         Zone('right', 'Right', ((0.5, 0), (1, 0), (1, 1), (0.5, 1))))


def floor(**kwargs):
    return PositionCalibration(mode='homography', image_points=QUAD, floor_width_m=6, floor_depth_m=8, **kwargs)


def test_projective_mapping_matches_opencv_across_floor():
    import cv2
    import numpy as np
    calibration = floor()
    target = np.float32(((0, 0), (6, 0), (6, 8), (0, 8)))
    expected = cv2.getPerspectiveTransform(np.float32(QUAD), target)
    for y in (0.2, 0.4, 0.6, 0.8):
        for x in (0.3, 0.5, 0.7):
            result = cv2.perspectiveTransform(np.float64([[[x, y]]]), expected)[0, 0]
            assert project((x, y), calibration) == pytest.approx(result, abs=1e-6)
    assert project((0.5, 0.05), calibration) is None
    assert project((0.5, 0.5), calibration) != pytest.approx((3, 4))


@pytest.mark.parametrize('points', [((0, 0), (1, 1), (0, 1), (1, 0)),
    ((0, 0), (1, 0), (0.5, 0.2), (0, 1)), ((0, 0), (0.1, 0), (0.2, 0), (0, 1)),
    ((0, 0), (1, 0), (float('nan'), 1), (0, 1)), ((0, 0), (1, 0), (1, 1)),
    ((0, 0), (1, 0), (1, 1), (0, 0)), ((0, 0), (0.001, 0), (0.001, 0.001), (0, 0.001))])
def test_reject_invalid_floor(points):
    with pytest.raises(ValueError):
        PositionCalibration(mode='homography', image_points=points, floor_width_m=6, floor_depth_m=8)


@pytest.mark.parametrize('changes', [{'floor_width_m': None}, {'floor_width_m': float('inf')},
    {'floor_depth_m': -2}, {'floor_boundary_margin_m': 4}, {'mode': 'magic'}, {'image_boundary_margin': 0}])
def test_reject_invalid_position_policy(changes):
    with pytest.raises(ValueError):
        replace(floor(), **changes)


def test_footpoint_uses_floor_anchor_instead_of_body_overlap():
    zones = (Zone('upper', 'Upper body', ((0, 0), (1, 0), (1, 0.5), (0, 0.5))),
             Zone('lower', 'Floor', ((0, 0.5), (1, 0.5), (1, 1), (0, 1))))
    person = Detection((0.2, 0.1, 0.4, 0.6), 0.95)
    assert associate([person], zones, Rules())['upper'][0] == State.OCCUPIED
    result = associate([person], zones, Rules(), PositionCalibration(mode='footpoint'))
    assert result['upper'][0] == State.EMPTY
    assert result['lower'][0] == State.OCCUPIED


def test_border_low_confidence_and_truncated_feet_never_assign_zone():
    policy = PositionCalibration(mode='footpoint')
    for person in (Detection((0.4, 0.2, 0.6, 0.8), 0.95), Detection((0.1, 0.2, 0.3, 0.8), 0.3),
                   Detection((0.4, 0.2, 0.6, 1.), 0.95)):
        result = associate([person], ZONES, Rules(), policy)
        assert not any(row[0] == State.OCCUPIED for row in result.values())
        assert any(row[0] == State.UNKNOWN for row in result.values())
    assert measured_position(Detection((0.1, 0.2, 0.3, 1), 0.9), policy)['reason'] == 'FEET_CLIPPED'


def test_floor_margin_is_measured_in_meters_and_groups_are_exclusive():
    calibration = PositionCalibration(mode='homography', image_points=((0, 0), (1, 0), (1, 1), (0, 1)), floor_width_m=10, floor_depth_m=10)
    uncertain = associate([Detection((0.4, 0.2, 0.598, 0.8), 0.95)], ZONES, Rules(), calibration)
    assert all(row[0] == State.UNKNOWN for row in uncertain.values())
    certain = associate([Detection((0.3, 0.2, 0.6, 0.8), 0.95)], ZONES, Rules(), calibration)
    assert certain['left'][0] == State.OCCUPIED
    assert certain['right'][0] == State.EMPTY
    duplicated = (ZONES[0], replace(ZONES[0], id='duplicate'))
    assert all(row[0] == State.UNKNOWN for row in associate([Detection((0.1, 0.2, 0.3, 0.8), 0.95)], duplicated, Rules(), calibration).values())


def test_floor_zones_must_fit_and_settings_roundtrip(tmp_path):
    with pytest.raises(ValueError, match='zona'):
        Settings(zones=ZONES, position=floor())
    zone = Zone('floor', 'Floor', QUAD)
    configuration = Settings(zones=(zone,), position=floor())
    values = asdict(configuration)
    values['database'] = str(tmp_path / 'data.sqlite3')
    path = tmp_path / 'settings.json'
    path.write_text(json.dumps(values))
    assert load_settings(path).position == configuration.position
    person = Detection((0.3, 0.05, 0.5, 0.08), 0.9)
    assert measured_position(person, floor())['reason'] == 'OUTSIDE_CALIBRATED_FLOOR'


class SuppliedTracks:
    def update(self, detections, *_):
        return detections


def test_pipeline_session_and_aggregate_share_calibration_and_freeze_at_border(tmp_path):
    config = Settings(database=tmp_path / 'data.sqlite3', zones=ZONES,
                      position=PositionCalibration(mode='footpoint'), rules=Rules(occupied_confirm_seconds=0.1))
    db = Database(config.database)
    pipeline = Pipeline(config, db, source='TEST', model_sha='f'*64, model_manifest={}, start=1_000_000)
    pipeline.tracker = SuppliedTracks()
    try:
        for i in range(16):
            result = pipeline.feed([Detection((0.1, 0.2, 0.3, 0.8), 0.95, 'A')], 1_000_000+i*200_000, i*200_000_000, i+1, 'camera')
        before = result['detections'][0]['workstation_times'][0]['presence_us']
        assert result['zones'][0]['state'] == State.OCCUPIED
        assert result['detections'][0]['position']['anchor'] == (0.2, 0.8)
        for i in range(16, 21):
            result = pipeline.feed([Detection((0.4, 0.2, 0.6, 0.8), 0.95, 'A')], 1_000_000+i*200_000, i*200_000_000, i+1, 'camera')
        assert all(row['state'] == State.UNKNOWN for row in result['zones'])
        session = next(iter(pipeline.sessions.sessions.values()))
        assert pipeline.sessions.snapshot(session)['zone_times']['left']['presence_us'] == before
        manifest = json.loads(db.conn.execute('SELECT runtime_manifest_json FROM engine_runs').fetchone()[0])
        assert manifest['position_calibration']['mode'] == 'footpoint'
    finally:
        pipeline.finish()
        db.close()


def test_live_profile_saves_reloads_and_legacy_still_valid(tmp_path):
    config = Settings(database=tmp_path / 'live.sqlite3')
    profile = {'width': 640, 'height': 480, 'camera_key': 'a'*64, 'zones': [asdict(Zone('floor', 'Floor', QUAD))], 'rules': asdict(Rules())}
    assert validate_calibration(profile)[0][0].id == 'floor'
    profile['position'] = asdict(floor())
    live = LiveController(config, None)
    live.save_calibration('WEBCAM_LIVE', profile)
    loaded = LiveController(config, None).snapshot()['calibrations']['WEBCAM_LIVE']
    assert loaded['position']['floor_width_m'] == 6
    assert loaded['position']['image_points'] == [list(p) for p in QUAD]


def test_floor_change_creates_new_auditable_configuration(tmp_path):
    config = Settings(database=tmp_path / 'revision.sqlite3', zones=(Zone('floor', 'Floor', QUAD),), position=floor())
    db = Database(config.database)
    try:
        for index, position in enumerate((floor(), floor(), replace(floor(), floor_width_m=7))):
            writer = db.begin_run(replace(config, position=position), source='TEST', model_sha='a'*64,
                                  model_manifest={}, start=1_000_000 + index*1_000_000)
            writer.finish(1_000_000 + index*1_000_000, 'COMPLETED')
        assert db.conn.execute('SELECT COUNT(*) FROM workspace_configurations').fetchone()[0] == 2
        assert db.conn.execute('SELECT COUNT(*) FROM rule_sets').fetchone()[0] == 2
    finally:
        db.close()


def test_calibration_api_validates_floor_and_preserves_it(tmp_path, monkeypatch):
    from contextlib import closing
    from fastapi.testclient import TestClient
    from cctv_tracker.api import create_app
    from cctv_tracker.dashboard import ReplayController
    from cctv_tracker.webcam import WebcamDetector
    monkeypatch.setattr(WebcamDetector, 'detect', lambda *args: {'width': 640, 'height': 480, 'detections': [], 'count': 0})
    config = Settings(database=tmp_path / 'api.sqlite3')
    with closing(Database(config.database)):
        pass
    controller = ReplayController(config)
    headers = {'Authorization': 'Bearer ' + 't'*32}
    profile = {'source': 'WEBCAM_LIVE', 'width': 640, 'height': 480, 'camera_key': 'b'*64,
               'zones': [asdict(Zone('floor', 'Floor', QUAD))], 'rules': asdict(Rules()), 'position': asdict(floor())}
    with TestClient(create_app(config.database, 't'*32, controller=controller)) as client:
        result = client.post('/pilot/v1/live/calibration', json=profile, headers=headers)
        assert result.status_code == 200, result.text
        assert result.json()['calibrations']['WEBCAM_LIVE']['position']['mode'] == 'homography'
        for position in ({**profile['position'], 'floor_width_m': 0},
                         {**profile['position'], 'image_points': [[0, 0], [1, 1], [0, 1], [1, 0]]},
                         {**profile['position'], 'arbitrary_matrix': [1]*9}):
            assert client.post('/pilot/v1/live/calibration', json={**profile, 'position': position}, headers=headers).status_code == 422
        outside = {**profile, 'zones': [asdict(ZONES[0])]}
        result = client.post('/pilot/v1/live/calibration', json=outside, headers=headers)
        assert result.status_code == 422
        assert 'di dalam' in result.json()['detail']
