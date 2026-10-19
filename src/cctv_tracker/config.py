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
class Settings:
    site_name: str = "Local pilot"
    camera_id: str = "camera-1"
    database: Path = field(default_factory=lambda: app_data() / "tracker.sqlite3")
    timezone: str = "Asia/Jakarta"
    inference_fps: int = 5
    capture_fps: int = 24
    capture_queue_size: int = 1
    native_threads: int = 1
    adaptive_inference: bool = False
    minimum_inference_fps: int = 1
    activity_enabled: bool = True
    activity_idle_seconds: float = 8
    activity_working_seconds: float = .8
    box_smoothing_ms: float = 80
    frame_stale_seconds: float = 1
    open_timeout_seconds: float = 10
    read_timeout_seconds: float = 5
    rules: Rules = field(default_factory=Rules)
    zones: tuple[Zone, ...] = ()

    def __post_init__(self):
        ZoneInfo(self.timezone)
        if not self.site_name.strip() or not self.camera_id.strip():
            raise ValueError("Site and camera IDs must not be empty")
        if not 1 <= self.inference_fps <= 30:
            raise ValueError("Inference FPS must be between 1 and 30")
        if type(self.capture_fps) is not int or not 1 <= self.capture_fps <= 24 or type(self.capture_queue_size) is not int or not 1 <= self.capture_queue_size <= 4:
            raise ValueError('Capture FPS must be 1..24 and queue capacity 1..4')
        if type(self.native_threads) is not int or not 1 <= self.native_threads <= 8:
            raise ValueError('Native threads must be 1..8')
        if type(self.adaptive_inference) is not bool or type(self.activity_enabled) is not bool or not 1 <= self.minimum_inference_fps <= self.inference_fps:
            raise ValueError('Invalid adaptive/activity configuration')
        if not all(math.isfinite(v) for v in (self.activity_idle_seconds,self.activity_working_seconds,self.box_smoothing_ms)) or not 2 <= self.activity_idle_seconds <= 120 or not .2 <= self.activity_working_seconds <= 10 or not 0 <= self.box_smoothing_ms <= 200:
            raise ValueError('Invalid motion confirmation or box smoothing settings')
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
    values["zones"] = tuple(Zone(**{**z, "polygon": tuple(tuple(p) for p in z["polygon"])}) for z in values.get("zones", []))
    return Settings(**values)
