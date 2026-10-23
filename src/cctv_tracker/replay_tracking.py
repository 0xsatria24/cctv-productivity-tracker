"""In-memory replay sessions, measured on media time and isolated from accounting."""
from dataclasses import dataclass, field, replace
import math
from threading import Lock
from time import monotonic
from uuid import UUID

from .config import Settings, Zone
from .positioning import PositionCalibration
from .workstations import WorkstationTimeline
from .sessions import SessionManager
from .vision import Tracker, frame_detections
from .reid.runtime import ReIdRuntime
from .reid.types import FrameToken


class ReplayConflict(ValueError):
    pass


@dataclass(frozen=True)
class ReplayFrame:
    replay_id: str
    generation: int
    sequence: int
    media_time: float
    calibration_revision: int = 0

    @classmethod
    def from_headers(cls, headers):
        names = ('x-replay-id', 'x-replay-generation', 'x-replay-sequence', 'x-replay-time')
        values = [headers.get(name) for name in names]
        if all(value is None for value in values):
            return None  # Older clients can still request stateless detection.
        if any(value is None or len(value) > 64 for value in values):
            raise ValueError('Envelope replay tidak lengkap')
        try:
            replay_id = str(UUID(values[0]))
            if not values[1].isdecimal() or not values[2].isdecimal():
                raise ValueError
            generation, sequence, media_time = int(values[1]), int(values[2]), float(values[3])
            if not (0 <= generation <= 1_000_000_000 and 1 <= sequence <= 1_000_000_000_000
                    and math.isfinite(media_time) and 0 <= media_time <= 2_592_000):
                raise ValueError
        except ValueError:
            raise ValueError('Envelope replay tidak valid') from None
        revision = headers.get('x-replay-calibration', '0')
        if len(revision) > 10 or not revision.isdecimal() or int(revision) > 1_000_000_000:
            raise ValueError('Revisi kalibrasi replay tidak valid')
        return cls(replay_id, generation, sequence, media_time, int(revision))


@dataclass
class ReplayStream:
    settings: Settings
    generation: int = -1
    sequence: int = 0
    media_time: float = -1
    touched: float = field(default_factory=monotonic)
    lock: object = field(default_factory=Lock)
    tracker: object = None
    sessions: object = None
    reid: object = None
    display_cache: dict = field(default_factory=dict)
    calibration_revision: int = 0
    calibration_generation: int = 0
    workstations: object = None


class ReplayTracking:
    def __init__(self, settings=None, *, capacity=64, idle_seconds=1800, reid_extractor=None):
        base = settings or Settings()
        # Replay presence never inherits calibrated work zones or lost-gap charging.
        self.settings = replace(base, zones=(), sessions=replace(base.sessions, count_lost_gap=False))
        self.capacity, self.idle_seconds = capacity, idle_seconds
        self.streams, self.lock = {}, Lock()
        self.reid_extractor = reid_extractor
        if self.settings.reid.mode != 'off' and self.reid_extractor is None:
            from .reid.openvino import OpenVinoExtractor
            self.reid_extractor = OpenVinoExtractor(self.settings.reid.manifest_path, device=self.settings.reid.device)

    def _acquire(self, replay_id):
        with self.lock:
            now = monotonic()
            for key, stream in list(self.streams.items()):
                if now - stream.touched > self.idle_seconds and not stream.lock.locked():
                    del self.streams[key]
            stream = self.streams.get(replay_id)
            if stream is None:
                if len(self.streams) >= self.capacity:
                    raise BlockingIOError('Terlalu banyak sesi replay; tutup replay yang tidak dipakai atau tunggu sesi kedaluwarsa')
                stream = self.streams[replay_id] = ReplayStream(
                    replace(self.settings, camera_id='replay:' + replay_id))
            if not stream.lock.acquire(blocking=False):
                raise BlockingIOError('Frame replay sebelumnya masih diproses')
            stream.touched = now
        return stream

    def configure(self, replay_id, payload):
        try:
            replay_id = str(UUID(replay_id))
            if not isinstance(payload, dict) or set(payload) != {'expected_revision', 'zones', 'association'}:
                raise ValueError
            revision, rows, mode = payload['expected_revision'], payload['zones'], payload['association']
            if type(revision) is not int or not 0 <= revision < 1_000_000_000:
                raise ValueError
            if mode not in {'bbox_overlap', 'footpoint'} or not isinstance(rows, list) or len(rows) > 16:
                raise ValueError
            zones = []
            for row in rows:
                if not isinstance(row, dict) or set(row) != {'id', 'name', 'polygon'}:
                    raise ValueError
                if any(not isinstance(row[key], str) or not 1 <= len(row[key].strip()) <= 80 for key in ('id', 'name')):
                    raise ValueError
                points = row['polygon']
                if not isinstance(points, list) or not 3 <= len(points) <= 32:
                    raise ValueError
                if any(not isinstance(p, list) or len(p) != 2 or any(type(v) not in (int, float) for v in p) for p in points):
                    raise ValueError
                zones.append(Zone(row['id'].strip(), row['name'].strip(), tuple(tuple(p) for p in points)))
            if len({z.id for z in zones}) != len(zones):
                raise ValueError
        except (ValueError, TypeError, KeyError, AttributeError):
            raise ValueError('Kalibrasi memerlukan ID unik, nama, dan poligon sederhana 3–32 titik (0–1), maksimal 16 zona') from None
        stream = self._acquire(replay_id)
        try:
            if revision != stream.calibration_revision:
                raise ReplayConflict('Revisi kalibrasi berubah; muat ulang replay')
            stream.settings = replace(stream.settings, zones=tuple(zones), position=PositionCalibration(mode=mode))
            stream.calibration_revision += 1
            stream.calibration_generation = stream.generation + 1
            stream.workstations = None
            return {'replay_id': replay_id, 'calibration_revision': stream.calibration_revision,
                    'minimum_generation': stream.calibration_generation, 'minimum_sequence': stream.sequence+1,
                    'zones': rows, 'association': mode,
                    'recorded': False, 'duration_accounting': False}
        finally:
            stream.lock.release()

    def calibration(self, replay_id):
        replay_id = str(UUID(replay_id))
        stream = self._acquire(replay_id)
        try:
            return {'calibration_revision': stream.calibration_revision, 'minimum_generation': stream.calibration_generation,
                    'minimum_sequence': stream.sequence+1,
                    'zones': [{'id': z.id, 'name': z.name, 'polygon': z.polygon} for z in stream.settings.zones],
                    'association': stream.settings.position.mode}
        finally:
            stream.lock.release()

    def process(self, detector, jpeg, frame):
        stream = self._acquire(frame.replay_id)
        try:
            if frame.calibration_revision != stream.calibration_revision or frame.generation < stream.calibration_generation:
                raise ReplayConflict('Frame memakai kalibrasi atau timeline lama')
            if frame.generation < stream.generation or frame.sequence <= stream.sequence:
                raise ReplayConflict('Frame replay lama ditolak')
            if frame.generation == stream.generation and frame.media_time <= stream.media_time:
                raise ReplayConflict('Waktu replay harus maju; mulai timeline baru setelah seek')
            if stream.tracker is None:
                stream.tracker = Tracker(stream.settings.inference_fps,
                                         stream.settings.rules.max_evidence_gap_seconds,
                                         rules=stream.settings.tracking)
                stream.sessions = SessionManager(stream.settings, continuation_confidence=min(
                    stream.settings.detection.tracking_confidence, stream.settings.rules.strong_confidence))
                stream.reid = ReIdRuntime(stream.settings.reid, self.reid_extractor)
            result = detector.detect(jpeg)
            detections = frame_detections(result)
            if frame.generation != stream.generation:
                stream.sessions.finish()
                stream.reid.clear()
                stream.display_cache.clear()
                stream.workstations = None
            generation = f'{frame.replay_id}:{frame.generation}'
            tracked = stream.tracker.update(detections, frame.media_time, generation)
            bindings = stream.sessions.update(tracked, round(frame.media_time * 1e6),
                                              round(frame.media_time * 1e9), generation,
                                              recover=stream.settings.reid.mode != 'active')
            token = FrameToken(stream.settings.camera_id, frame.replay_id, generation,
                               frame.sequence, round(frame.media_time*1e9), stream.sessions.mapping_version)
            stage = stream.reid.prepare(jpeg, tracked, token, stream.sessions, bindings, replay=True)
            bindings = stream.reid.apply(stage, stream.sessions, bindings)
            reid_report = stream.reid.commit(stage, set(stream.sessions.sessions))
            rows = []
            for detection, session in bindings:
                if detection.tracking_only:
                    continue
                rows.append({'box': detection.box, 'confidence': detection.confidence,
                             'track_id': detection.track_id,
                             'session_id': session.session_id if session else None,
                             'accumulated_duration_us': session.accumulated_ns // 1000 if session else None,
                             'evidence_state': 'MEASURED' if session is None or session.last_observation_strong else 'WEAK',
                             'recovery_pending': bool(session and session.candidate_id)})
            display_rows = self._display_rows(stream, rows, frame.media_time)
            sessions = [{'session_id': session.session_id, 'status': session.status,
                         'recovery_pending': bool(session.candidate_id),
                         'evidence_state': 'MEASURED' if session.last_observation_strong else 'WEAK',
                         'accumulated_duration_us': session.accumulated_ns // 1000,
                         'first_seen_media_seconds': session.first_ns / 1e9,
                         'last_seen_media_seconds': session.last_ns / 1e9}
                        for session in stream.sessions.sessions.values()]
            if stream.workstations is None:
                stream.workstations = WorkstationTimeline(stream.settings)
            workstation_rows = stream.workstations.update([d for d in detections if not d.tracking_only], frame)
            stream.sessions.checkpoint()
            stream.generation, stream.sequence, stream.media_time = frame.generation, frame.sequence, frame.media_time
            return {**result, 'detections': rows, 'count': len(rows), 'sessions': sessions,
                    'display_detections': display_rows,
                    'workstations': workstation_rows,
                    'calibration_revision': stream.calibration_revision,
                    'reid': reid_report,
                    'session_metrics': dict(stream.sessions.metrics),
                    'tracking': dict(stream.tracker.metrics),
                    'mapping_version': stream.sessions.mapping_version,
                    'replay_id': frame.replay_id, 'generation': frame.generation,
                    'frame_sequence': frame.sequence, 'media_time_seconds': frame.media_time,
                    'source': 'LOCAL_VIDEO_REPLAY', 'recorded': False,
                    'tracking_supported': True, 'duration_accounting': False,
                    'duration_basis': 'observed_media_time',
                    'recovery_window_seconds': stream.settings.sessions.motion_recovery_seconds}
        finally:
            stream.touched = monotonic()
            stream.lock.release()

    @staticmethod
    def _display_rows(stream, rows, at):
        """Short visual carry only. Never feed predictions back into sessions."""
        display = [{**row, 'measured': True} for row in rows]
        current = {row['session_id'] for row in rows if row['session_id']}
        for sid, (seen, previous) in list(stream.display_cache.items()):
            age = at-seen
            if age > .4 or age < 0 or sid not in stream.sessions.sessions:
                del stream.display_cache[sid]
                continue
            if sid in current:
                continue
            box = previous['box']
            # Do not ghost an exit or overlap a newly measured person.
            if min(box[:2]) <= .02 or max(box[2:]) >= .98:
                continue
            overlaps = any(min(box[2], row['box'][2]) > max(box[0], row['box'][0])
                           and min(box[3], row['box'][3]) > max(box[1], row['box'][1]) for row in rows)
            if not overlaps:
                display.append({**previous, 'measured': False, 'evidence_state': 'PREDICTED',
                                'prediction_age_seconds': age})
        for row in rows:
            if row['session_id']:
                stream.display_cache[row['session_id']] = (at, dict(row))
        return display
