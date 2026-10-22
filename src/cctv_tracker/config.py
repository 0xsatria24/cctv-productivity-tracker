from dataclasses import dataclass, field
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import json
import math
import os


def app_data() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local" / "share"))
    return base / "CCTVTracker"


def timestamp(value: str) -> int:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("Timestamp requires an explicit timezone")
    return int(dt.timestamp() * 1_000_000)


@dataclass(frozen=True)
class Zone:
    id: str
    name: str
    polygon: tuple[tuple[float, float], ...]
    exclusive_group: str = "desks"

    def __post_init__(self):
        from .domain.geometry import valid_polygon
        if not self.id or not self.name or not valid_polygon(self.polygon):
            raise ValueError("Zone requires an ID, name, and simple normalized polygon")


@dataclass(frozen=True)
class Rules:
    occupied_confirm_seconds: float = 2
    empty_confirm_seconds: float = 5
    max_evidence_gap_seconds: float = 1
    association_overlap: float = 0.25
    ambiguity_margin: float = 0.1
    strong_confidence: float = 0.5

    def __post_init__(self):
        values = (self.occupied_confirm_seconds, self.empty_confirm_seconds, self.max_evidence_gap_seconds)
        if any(not math.isfinite(v) or v <= 0 for v in values):
            raise ValueError("Confirmation and gap limits must be positive and finite")
        if any(not math.isfinite(v) or not 0 < v <= 1 for v in (self.association_overlap, self.ambiguity_margin, self.strong_confidence)):
            raise ValueError("Confidence and overlap values must be in (0, 1]")


@dataclass(frozen=True)
class SessionRules:
    grace_period_seconds: float = 10
    motion_recovery_seconds: float = 3.5
    recovery_confirm_observations: int = 3
    recovery_confirm_seconds: float = 0.2
    recovery_confirmation_window_seconds: float = 1
    active_position_tolerance: float = 0.12
    recovery_position_tolerance: float = 0.035
    recovery_progress_tolerance: float = 0.35
    minimum_motion_speed: float = 0.015
    minimum_match_score: float = 0.55
    match_margin: float = 0.15
    roi_exit_observations: int = 3
    max_sessions: int = 256
    history_size: int = 8
    count_lost_gap: bool = False
    diagnostics: bool = False

    def __post_init__(self):
        for name in ('grace_period_seconds', 'motion_recovery_seconds', 'recovery_confirm_seconds',
                     'recovery_confirmation_window_seconds', 'active_position_tolerance',
                     'recovery_position_tolerance', 'minimum_motion_speed'):
            value = getattr(self, name)
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f'{name} must be positive and finite')
        if self.motion_recovery_seconds > self.grace_period_seconds:
            raise ValueError('Recovery window must not exceed session retention')
        if self.recovery_confirm_seconds > self.recovery_confirmation_window_seconds:
            raise ValueError('Confirmation must fit within its window')
        for name, low, high in (('recovery_confirm_observations', 2, 30), ('roi_exit_observations', 2, 30),
                                ('max_sessions', 2, 2048), ('history_size', 3, 32)):
            value = getattr(self, name)
            if type(value) is not int or not low <= value <= high:
                raise ValueError(f'{name} outside supported range')
        if any(not math.isfinite(v) or not 0 < v < 1 for v in (self.minimum_match_score, self.match_margin, self.recovery_progress_tolerance)):
            raise ValueError('Session score and margin must be in (0,1)')
        if type(self.count_lost_gap) is not bool or type(self.diagnostics) is not bool:
            raise ValueError('Session flags must be boolean')


@dataclass(frozen=True)
class Settings:
    site_name: str = "Local pilot"
    camera_id: str = "camera-1"
    database: Path = field(default_factory=lambda: app_data() / "tracker.sqlite3")
    timezone: str = "Asia/Jakarta"
    inference_fps: int = 5
    frame_stale_seconds: float = 1
    open_timeout_seconds: float = 10
    read_timeout_seconds: float = 5
    rules: Rules = field(default_factory=Rules)
    zones: tuple[Zone, ...] = ()
    sessions: SessionRules = field(default_factory=SessionRules)

    def __post_init__(self):
        ZoneInfo(self.timezone)
        if not self.site_name.strip() or not self.camera_id.strip():
            raise ValueError("Site and camera IDs must not be empty")
        if not 1 <= self.inference_fps <= 30:
            raise ValueError("Inference FPS must be between 1 and 30")
        if any(not math.isfinite(v) or v <= 0 for v in (self.frame_stale_seconds, self.open_timeout_seconds, self.read_timeout_seconds)):
            raise ValueError("Timeouts must be positive and finite")
        if len({z.id for z in self.zones}) != len(self.zones):
            raise ValueError("Duplicate zone IDs")
        # Multiple CPUs can read WAL, but an active database must remain local.
        if str(self.database).startswith(("\\\\", "//")):
            raise ValueError("Database must be on a local disk")


def load_settings(path: Path) -> Settings:
    raw = json.loads(path.read_text(encoding="utf-8"))
    allowed = set(Settings.__dataclass_fields__)
    if not isinstance(raw, dict) or set(raw) - allowed:
        raise ValueError("Unsupported configuration fields")
    values = dict(raw)
    if "database" in values:
        values["database"] = Path(values["database"]).expanduser().resolve()
    values["rules"] = Rules(**values.get("rules", {}))
    values["sessions"] = SessionRules(**values.get("sessions", {}))
    values["zones"] = tuple(Zone(**{**z, "polygon": tuple(tuple(p) for p in z["polygon"])}) for z in values.get("zones", []))
    return Settings(**values)
