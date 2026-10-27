"""Visible marker check-ins; registration is separate from workstation occupancy."""
from collections import Counter
from time import perf_counter
from threading import Lock

from .positioning import contains

DICTIONARY = 'DICT_4X4_50'


def validate_registry(rows):
    if not isinstance(rows, list) or len(rows) > 50:
        raise ValueError('Maksimal 50 marker ArUco')
    result = []
    for row in rows:
        if (not isinstance(row, dict) or set(row) != {'marker_id', 'label'}
                or type(row['marker_id']) is not int or not 0 <= row['marker_id'] < 50
                or not isinstance(row['label'], str) or not 1 <= len(row['label'].strip()) <= 80):
            raise ValueError('Marker memerlukan ID 0–49 dan nama 1–80 karakter')
        result.append({'marker_id': row['marker_id'], 'label': row['label'].strip()})
    if len({row['marker_id'] for row in result}) != len(result):
        raise ValueError('ID marker harus unik')
    return result


def marker_png(marker_id):
    import cv2
    if type(marker_id) is not int or not 0 <= marker_id < 50:
        raise ValueError('ID marker harus 0–49')
    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    marker = cv2.aruco.generateImageMarker(dictionary, marker_id, 400)
    image = cv2.copyMakeBorder(marker, 56, 56, 56, 56, cv2.BORDER_CONSTANT, value=255)
    ok, encoded = cv2.imencode('.png', image)
    if not ok:
        raise RuntimeError('Marker tidak dapat dibuat')
    return encoded.tobytes()


class ArucoReader:
    def __init__(self):
        self.detector = None
        self.lock = Lock()

    def detect(self, jpeg):
        with self.lock:
            return self._detect(jpeg)

    def _detect(self, jpeg):
        import cv2
        import numpy as np
        started = perf_counter()
        if self.detector is None:
            if not hasattr(cv2, 'aruco'):
                raise RuntimeError('Runtime OpenCV belum mendukung ArUco')
            dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
            self.detector = cv2.aruco.ArucoDetector(dictionary, cv2.aruco.DetectorParameters())
        frame = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_GRAYSCALE)
        if frame is None:
            raise ValueError('Frame marker tidak dapat dibaca')
        height, width = frame.shape
        corners, identifiers, _ = self.detector.detectMarkers(frame)
        rows = []
        for marker, identifier in zip(corners, identifiers.flatten() if identifiers is not None else []):
            points = [(float(x)/width, float(y)/height) for x, y in marker[0]]
            rows.append({'marker_id': int(identifier), 'corners': points,
                         'center': [sum(p[0] for p in points)/4, sum(p[1] for p in points)/4]})
        return {'status': 'READY', 'dictionary': DICTIONARY, 'markers': rows,
                'elapsed_ms': round((perf_counter()-started)*1000, 2)}


class MarkerCheckIns:
    def __init__(self, registry):
        self.registry = {row['marker_id']: row['label'] for row in registry}
        self.registered, self.pending = {}, {}
        self.last_time = None

    def update(self, markers, workstations, zones, at, people=()):
        if self.last_time is not None and at-self.last_time > 1:
            self.pending.clear()
        self.last_time = at
        by_zone = {zone.id: [] for zone in zones}
        counts = Counter(row['marker_id'] for row in markers)
        for marker in markers:
            candidates = [zone.id for zone in zones if contains(marker['center'], zone.polygon)]
            if len(candidates) == 1:
                by_zone[candidates[0]].append(marker['marker_id'])
        rows = []
        for station in workstations:
            sid = station['zone_id']
            visible = by_zone[sid]
            marker_id = visible[0] if len(visible) == 1 else None
            selected = next((m for m in markers if m['marker_id'] == marker_id), None)
            owners = [person for person in people if selected and not person.tracking_only
                      and person.box[0] <= selected['center'][0] <= person.box[2]
                      and person.box[1] <= selected['center'][1] <= person.box[3]]
            eligible = (marker_id in self.registry and counts[marker_id] == 1
                        and len(owners) == 1 and station['state'] == 'OCCUPIED' and station['count'] == 1)
            state = 'UNREGISTERED'
            if station['state'] == 'EMPTY':
                self.registered.pop(sid, None)
            if eligible:
                previous = self.pending.get(sid)
                count, first = (previous[1]+1, previous[2]) if previous and previous[0] == marker_id else (1, at)
                self.pending[sid] = (marker_id, count, first)
                if count >= 3 and at-first >= .4-1e-8:
                    for other, entry in list(self.registered.items()):
                        if other != sid and entry['marker_id'] == marker_id:
                            del self.registered[other]
                    entry = self.registered.get(sid)
                    checked = entry['checked_in_media_seconds'] if entry and entry['marker_id'] == marker_id else at
                    self.registered[sid] = {'marker_id': marker_id, 'label': self.registry[marker_id],
                        'checked_in_media_seconds': checked, 'last_seen_media_seconds': at}
                    state = 'VERIFIED_MARKER'
                else:
                    state = 'CONFIRMING'
            else:
                self.pending.pop(sid, None)
                if len(visible) > 1 or (marker_id is not None and counts[marker_id] > 1) or (station['count'] or 0) > 1:
                    state = 'AMBIGUOUS'
                elif visible and marker_id not in self.registry:
                    state = 'UNLISTED_MARKER'
                elif visible and len(owners) != 1:
                    state = 'UNASSOCIATED'
            rows.append({**station, 'checkin': {'state': state,
                         'registered': self.registered.get(sid), 'visible_marker_ids': visible}})
        for row in rows:
            row['checkin']['registered'] = self.registered.get(row['zone_id'])
        return rows
