"""Shared workstation evidence policy for replay and live source adapters."""
from dataclasses import asdict

from .aruco import DICTIONARY
from .config import Rules
from .domain.occupancy import State
from .vision import associate

WORKSTATION_FPS = 2
DEFAULT_WORKSTATION_RULES = Rules()


def workstation_policy(settings):
    return {'sample_fps': WORKSTATION_FPS, 'rules': asdict(settings.rules),
            'aruco_dictionary': DICTIONARY}


def workstation_observations(detections, settings, unavailable=None):
    if unavailable:
        return {zone.id: (State.UNKNOWN, None, unavailable) for zone in settings.zones}
    return associate([d for d in detections if not d.tracking_only], settings.zones,
                     settings.rules, settings.position)


def workstation_markers(reader, jpeg, configured, unavailable=None):
    base = {'dictionary': DICTIONARY, 'markers': []}
    if not configured:
        return {**base, 'status': 'NOT_CONFIGURED'}
    if unavailable or jpeg is None:
        return {**base, 'status': 'NO_FRAME'}
    try:
        return {**base, **reader.detect(jpeg)}
    except Exception as error:
        return {**base, 'status': 'UNAVAILABLE', 'message': str(error)}


def workstation_checkins(checkins, markers, rows, detections, settings, at):
    people = [d for d in detections if not d.tracking_only
              and d.confidence >= settings.rules.strong_confidence]
    return checkins.update(markers['markers'], rows, settings.zones, at, people)
