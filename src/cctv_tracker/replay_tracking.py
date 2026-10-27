"""In-memory replay sessions, measured on media time and isolated from accounting."""
from dataclasses import dataclass, field, replace
from concurrent.futures import Future
from copy import deepcopy
import math
from threading import Lock, Thread
from time import monotonic
from uuid import UUID

from .config import Settings, Zone
from .positioning import PositionCalibration
from .workstations import WorkstationTimeline
from .aruco import ArucoReader, MarkerCheckIns, validate_registry
from .replay_state import ReplayStateStore
from .sessions import SessionManager
from .vision import Tracker, frame_detections
from .reid.runtime import ReIdRuntime
from .reid.types import FrameToken
from .workstation_engine import workstation_markers, workstation_checkins


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
    reid_pending: object = None
    display_cache: dict = field(default_factory=dict)
    calibration_revision: int = 0
    calibration_generation: int = 0
    workstations: object = None
    area_workstations: object = None
    markers: list = field(default_factory=list)
    checkins: object = None
    analysis_mode: str | None = None
    saved_at: float = 0
    save_error: str | None = None


class ReplayTracking:
    def __init__(self, settings=None, *, capacity=64, idle_seconds=1800, reid_extractor=None, background_reid=False, aruco_reader=None, state_dir=None):
        base = settings or Settings()
        # Replay presence never inherits calibrated work zones or lost-gap charging.
        self.settings = replace(base, zones=(), sessions=replace(base.sessions, count_lost_gap=False))
        self.capacity, self.idle_seconds = capacity, idle_seconds
        self.streams, self.lock = {}, Lock()
        self.reid_extractor = reid_extractor
        self.background_reid = background_reid
        self.reid_worker = Lock()
        self.aruco_reader = aruco_reader or ArucoReader()
        self.store = ReplayStateStore(state_dir) if state_dir else None
        if self.settings.reid.mode != 'off' and self.reid_extractor is None:
            from .reid.openvino import OpenVinoExtractor
            self.reid_extractor = OpenVinoExtractor(self.settings.reid.manifest_path, device=self.settings.reid.device)

    def _acquire(self, replay_id):
        replay_id = str(UUID(replay_id))
        with self.lock:
            now = monotonic()
            for key, stream in list(self.streams.items()):
                if now - stream.touched > self.idle_seconds and not stream.lock.locked():
                    self._save(key, stream, force=True)
                    del self.streams[key]
            stream = self.streams.get(replay_id)
            if stream is None:
                if len(self.streams) >= self.capacity:
                    raise BlockingIOError('Terlalu banyak sesi replay; tutup replay yang tidak dipakai atau tunggu sesi kedaluwarsa')
                stream = ReplayStream(replace(self.settings, camera_id='replay:' + replay_id))
                saved = self.store.read(replay_id) if self.store else None
                if saved:
                    _, zones, _, mode, markers = self._parse_calibration({'expected_revision': 0, **saved['calibration']})
                    stream.settings = replace(stream.settings, zones=tuple(zones), position=PositionCalibration(mode=mode))
                    stream.markers = markers
                    stream.calibration_revision = 1
                    stream.workstations = WorkstationTimeline(stream.settings, unique_media=True)
                    stream.workstations.restore(saved['workstations'])
                    stream.area_workstations = stream.workstations
                self.streams[replay_id] = stream
            if not stream.lock.acquire(blocking=False):
                raise BlockingIOError('Frame replay sebelumnya masih diproses')
            stream.touched = now
        return stream

    @staticmethod
    def _parse_calibration(payload):
        try:
            if (not isinstance(payload, dict) or not {'expected_revision', 'zones', 'association'} <= set(payload)
                    or set(payload)-{'expected_revision', 'zones', 'association', 'markers'}):
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
        markers = validate_registry(payload.get('markers', []))
        return revision, zones, rows, mode, markers

    def _save(self, replay_id, stream, *, force=False):
        timeline = stream.area_workstations
        if self.store and timeline and (force or monotonic()-stream.saved_at >= 2):
            try:
                self.store.write(replay_id, {'zones': [{'id': z.id, 'name': z.name, 'polygon': z.polygon} for z in stream.settings.zones],
                    'association': stream.settings.position.mode, 'markers': stream.markers}, timeline)
                stream.saved_at, stream.save_error = monotonic(), None
            except OSError:
                stream.save_error = 'Hasil belum tersimpan ke disk. Unduh CSV sebelum menutup video.'

    def configure(self, replay_id, payload):
        replay_id = str(UUID(replay_id))
        revision, zones, rows, mode, markers = self._parse_calibration(payload)
        stream = self._acquire(replay_id)
        try:
            if revision != stream.calibration_revision:
                raise ReplayConflict('Revisi kalibrasi berubah; muat ulang replay')
            changed = (stream.settings.zones != tuple(zones) or stream.settings.position.mode != mode or stream.markers != markers)
            if changed:
                settings = replace(stream.settings, zones=tuple(zones), position=PositionCalibration(mode=mode))
                if stream.area_workstations:
                    stream.area_workstations.reconfigure(settings)
                else:
                    stream.area_workstations = WorkstationTimeline(settings, unique_media=True)
                stream.workstations = stream.area_workstations
                stream.settings = settings
                stream.calibration_revision += 1
                stream.calibration_generation = stream.generation + 1
                stream.markers = markers
                stream.checkins = None
                self._save(replay_id, stream, force=True)
            return {'replay_id': replay_id, 'calibration_revision': stream.calibration_revision,
                    'minimum_generation': stream.calibration_generation, 'minimum_sequence': stream.sequence+1,
                    'zones': rows, 'association': mode, 'markers': markers,
                    'changed': changed, 'workstations': stream.area_workstations.snapshot() if stream.area_workstations else [],
                    'workstation_history': stream.area_workstations.history if stream.area_workstations else [], 'save_error': stream.save_error,
                    'recorded': False, 'duration_accounting': False}
        finally:
            stream.lock.release()

    def calibration(self, replay_id):
        replay_id = str(UUID(replay_id))
        stream = self._acquire(replay_id)
        try:
            return {'calibration_revision': stream.calibration_revision, 'minimum_generation': max(stream.calibration_generation, stream.generation+1),
                    'minimum_sequence': stream.sequence+1,
                    'zones': [{'id': z.id, 'name': z.name, 'polygon': z.polygon} for z in stream.settings.zones],
                    'association': stream.settings.position.mode, 'markers': stream.markers,
                    'workstations': stream.area_workstations.snapshot() if stream.area_workstations else [],
                    'workstation_history': stream.area_workstations.history if stream.area_workstations else [], 'save_error': stream.save_error}
        finally:
            stream.lock.release()

    def checkpoint(self, replay_id):
        stream = self._acquire(replay_id)
        try:
            self._save(replay_id, stream, force=True)
            return {'saved': bool(self.store and stream.area_workstations and not stream.save_error), 'save_error': stream.save_error}
        finally:
            stream.lock.release()

    def flush(self):
        for replay_id, stream in list(self.streams.items()):
            if stream.lock.acquire(blocking=False):
                try:
                    self._save(replay_id, stream, force=True)
                finally:
                    stream.lock.release()

    def process(self, detector, jpeg, frame, analysis_mode='person'):
        stream = self._acquire(frame.replay_id)
        try:
            if analysis_mode not in {'person', 'workstation'}:
                raise ValueError('Mode analisis harus person atau workstation')
            if frame.calibration_revision != stream.calibration_revision or frame.generation < stream.calibration_generation:
                raise ReplayConflict('Frame memakai kalibrasi atau timeline lama')
            if frame.generation < stream.generation or frame.sequence <= stream.sequence:
                raise ReplayConflict('Frame replay lama ditolak')
            if frame.generation == stream.generation and frame.media_time <= stream.media_time:
                raise ReplayConflict('Waktu replay harus maju; mulai timeline baru setelah seek')
            if frame.generation == stream.generation and stream.analysis_mode != analysis_mode:
                raise ReplayConflict('Perubahan mode memerlukan timeline baru')
            if analysis_mode == 'workstation':
                return self._workstation_frame(stream, detector, jpeg, frame)
            if stream.tracker is None:
                stream.tracker = Tracker(stream.settings.inference_fps,
                                         stream.settings.rules.max_evidence_gap_seconds,
                                         stream.settings.track_recovery_seconds,
                                         rules=stream.settings.tracking)
                stream.sessions = SessionManager(stream.settings, continuation_confidence=min(
                    stream.settings.detection.tracking_confidence, stream.settings.rules.strong_confidence))
                stream.reid = ReIdRuntime(stream.settings.reid, self.reid_extractor)
            result = detector.detect(jpeg)
            detections = frame_detections(result)
            if frame.generation != stream.generation:
                stream.sessions.finish()
                stream.reid = ReIdRuntime(stream.settings.reid, self.reid_extractor)
                stream.reid_pending = None
                stream.display_cache.clear()
                stream.workstations = None
            generation = f'{frame.replay_id}:{frame.generation}'
            tracked = stream.tracker.update(detections, frame.media_time, generation)
            bindings = stream.sessions.update(tracked, round(frame.media_time * 1e6),
                                              round(frame.media_time * 1e9), generation,
                                              recover=stream.settings.reid.mode != 'active')
            token = FrameToken(stream.settings.camera_id, frame.replay_id, generation,
                               frame.sequence, round(frame.media_time*1e9), stream.sessions.mapping_version)
            if self.background_reid and stream.settings.reid.mode != 'off':
                bindings, reid_report = self._background_reid(stream, jpeg, tracked, token, bindings)
            else:
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
                             'evidence_state': 'MEASURED' if detection.confidence >= stream.settings.rules.strong_confidence else 'WEAK',
                             'recovery_pending': bool(session and session.candidate_id)})
            display_rows = self._display_rows(stream, rows, frame.media_time)
            for detection, session in bindings:
                if detection.tracking_only and detection.track_id:
                    # Weak observations are visible but never become accounting evidence.
                    display_rows = [r for r in display_rows if not (
                        r.get('track_id') == detection.track_id and not r['measured'])]
                    display_rows.append({'box': detection.box, 'confidence': detection.confidence,
                        'track_id': detection.track_id, 'session_id': session.session_id if session else None,
                        'accumulated_duration_us': session.accumulated_ns // 1000 if session else None,
                        'measured': True, 'evidence_state': 'WEAK'})
            sessions = [{'session_id': session.session_id, 'status': session.status,
                         'recovery_pending': bool(session.candidate_id),
                         'evidence_state': 'MEASURED' if session.last_observation_strong else 'WEAK',
                         'accumulated_duration_us': session.accumulated_ns // 1000,
                         'observed_duration_us': session.observed_ns // 1000,
                         'total_elapsed_us': max(0, round(frame.media_time*1e9) - session.first_ns) // 1000,
                         'absence_duration_us': max(0, round(frame.media_time*1e9) - session.last_strong_ns) // 1000,
                         'first_seen_media_seconds': session.first_ns / 1e9,
                         'last_seen_media_seconds': session.last_seen / 1e6}
                        for session in stream.sessions.sessions.values()]
            if stream.workstations is None:
                stream.workstations = WorkstationTimeline(stream.settings)
            workstation_rows = stream.workstations.update([d for d in detections if not d.tracking_only], frame)
            stream.sessions.checkpoint()
            stream.generation, stream.sequence, stream.media_time = frame.generation, frame.sequence, frame.media_time
            stream.analysis_mode = 'person'
            return {**result, 'detections': rows, 'count': len(rows), 'sessions': sessions,
                    'display_detections': display_rows,
                    'display_prediction_seconds': stream.settings.tracking.display_prediction_seconds,
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

    def _workstation_frame(self, stream, detector, jpeg, frame):
        result = detector.detect(jpeg)
        detections = [d for d in frame_detections(result) if not d.tracking_only]
        markers = workstation_markers(self.aruco_reader, jpeg, bool(stream.markers))
        stream.workstations = stream.area_workstations
        if frame.generation != stream.generation:
            if stream.workstations and not stream.workstations.unique_media:
                stream.workstations = None
            stream.checkins = None
            stream.display_cache.clear()
            stream.reid_pending = None
            if stream.sessions:
                stream.sessions.finish()
        if stream.workstations is None:
            stream.workstations = WorkstationTimeline(stream.settings, unique_media=True)
        stream.area_workstations = stream.workstations
        if stream.checkins is None:
            stream.checkins = MarkerCheckIns(stream.markers)
        workstations = stream.workstations.update(detections, frame)
        workstations = workstation_checkins(stream.checkins, markers, workstations, detections, stream.settings, frame.media_time)
        stream.generation, stream.sequence, stream.media_time = frame.generation, frame.sequence, frame.media_time
        stream.analysis_mode = 'workstation'
        self._save(frame.replay_id, stream)
        return {**result, 'analysis_mode': 'workstation', 'workstations': workstations, 'aruco': markers,
                'sessions': [], 'display_detections': [], 'reid': {'mode': 'off', 'status': 'OFF', 'decisions': []},
                'calibration_revision': stream.calibration_revision, 'replay_id': frame.replay_id,
                'generation': frame.generation, 'frame_sequence': frame.sequence, 'media_time_seconds': frame.media_time,
                'tracking_supported': False, 'recorded': False, 'duration_accounting': False,
                'workstation_history': stream.workstations.history, 'save_error': stream.save_error,
                'source': 'LOCAL_VIDEO_REPLAY', 'duration_basis': 'observed_media_time'}

    def _background_reid(self, stream, jpeg, tracked, token, bindings):
        runtime = stream.reid
        report = {'mode': runtime.rules.mode, 'status': 'PROCESSING', 'decisions': [],
                  'gallery_sessions': len(runtime.gallery.entries)}
        pending = stream.reid_pending
        if pending is not None and pending.done():
            stream.reid_pending = None
            stage = pending.result()
            original = stage['token']
            current = {s.session_id: i for i, (_, s) in enumerate(bindings) if s}
            fresh = (original.scope == token.scope and original.mapping_version == token.mapping_version
                     and 0 <= token.monotonic_ns-original.monotonic_ns <= 500_000_000)
            decisions = []
            for decision in stage['report']['decisions']:
                index = current.get(decision['candidate_session_id'])
                target = stream.sessions.sessions.get(decision['target_session_id'])
                if not fresh or index is None or target is None or target.status != 'LOST':
                    continue
                detection, candidate = bindings[index]
                scorer = runtime._short_occlusion_score if runtime.rules.recovery_policy == 'short_occlusion' else stream.sessions.recovery_score
                if scorer(target, candidate, detection, token.monotonic_ns) is not None:
                    decisions.append({**decision, 'detection_index': index})
            stage['report']['decisions'] = decisions
            if not fresh:
                stage['votes'] = {}
            # Recovery uses today's observation time; gallery samples retain their original tokens.
            stage['token'] = token
            bindings = runtime.apply(stage, stream.sessions, bindings)
            stage['results'] = [(sid, result) for sid, result in stage['results'] if sid in stream.sessions.sessions]
            report = runtime.commit(stage, set(stream.sessions.sessions))
        if stream.reid_pending is None and self.reid_worker.acquire(blocking=False):
            try:
                manager, snapshot_bindings = deepcopy((stream.sessions, bindings))
                future = Future()
                stream.reid_pending = future
                def work():
                    try:
                        future.set_result(runtime.prepare(jpeg, tracked, token, manager, snapshot_bindings, replay=True))
                    except Exception as error:
                        future.set_exception(error)
                    finally:
                        self.reid_worker.release()
                Thread(target=work, name='replay-reid', daemon=True).start()
            except Exception:
                self.reid_worker.release()
                raise
        return bindings, report

    @staticmethod
    def _display_rows(stream, rows, at):
        """Short visual carry only. Never feed predictions back into sessions."""
        display = [{**row, 'measured': True} for row in rows]
        current = {row['session_id'] for row in rows if row['session_id']}
        for sid, (seen, previous) in list(stream.display_cache.items()):
            age = at-seen
            if age > stream.settings.tracking.display_prediction_seconds or age < 0 or sid not in stream.sessions.sessions:
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
