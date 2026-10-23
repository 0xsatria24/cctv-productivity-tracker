from dataclasses import dataclass
import math


@dataclass(frozen=True)
class ReIdRules:
    mode: str = 'off'
    recovery_policy: str = 'motion'
    manifest_path: str | None = None
    device: str = 'CPU'
    sample_interval_seconds: float = 0.3
    max_crops_per_frame: int = 8
    min_width: int = 32
    min_height: int = 96
    min_confidence: float = 0.65
    min_blur_score: float = 30
    max_overlap: float = 0.2
    max_gallery_sessions: int = 128
    max_gallery_samples: int = 4
    min_gallery_samples: int = 2
    ttl_seconds: float = 30
    max_gap_seconds: float = 3.5
    min_similarity: float = 0.85
    min_margin: float = 0.08
    confirm_observations: int = 3
    confirm_seconds: float = 0.6
    max_extra_latency_ms: float = 150

    def __post_init__(self):
        if self.mode not in {'off', 'shadow', 'active'}:
            raise ValueError('ReID supports off/shadow/active')
        if self.recovery_policy not in {'motion', 'short_occlusion'}:
            raise ValueError('Unsupported ReID recovery policy')
        if self.device not in {'CPU', 'GPU'}:
            raise ValueError('Unsupported ReID device')
        if self.mode != 'off' and (not isinstance(self.manifest_path, str) or not self.manifest_path.strip()):
            raise ValueError('Enabled ReID requires a local model manifest')
        for name, low, high in (('max_crops_per_frame', 1, 64), ('min_width', 8, 512), ('min_height', 16, 1024),
                                ('max_gallery_sessions', 1, 2048), ('max_gallery_samples', 2, 32),
                                ('min_gallery_samples', 2, 32), ('confirm_observations', 2, 30)):
            value = getattr(self, name)
            if type(value) is not int or not low <= value <= high:
                raise ValueError(f'Invalid ReID {name}')
        for name in ('sample_interval_seconds', 'ttl_seconds', 'max_gap_seconds', 'confirm_seconds', 'max_extra_latency_ms'):
            value = getattr(self, name)
            if isinstance(value, bool) or not math.isfinite(value) or not 0 < value <= 60000:
                raise ValueError(f'Invalid ReID {name}')
        if self.min_gallery_samples > self.max_gallery_samples or self.confirm_seconds > self.max_gap_seconds or self.max_gap_seconds > self.ttl_seconds:
            raise ValueError('Inconsistent ReID confirmation/gallery windows')
        for name in ('min_confidence', 'max_overlap', 'min_similarity', 'min_margin'):
            value = getattr(self, name)
            if isinstance(value, bool) or not math.isfinite(value) or not 0 < value < 1:
                raise ValueError(f'Invalid ReID {name}')
        if not math.isfinite(self.min_blur_score) or not 0 <= self.min_blur_score <= 10000:
            raise ValueError('Invalid ReID blur threshold')
