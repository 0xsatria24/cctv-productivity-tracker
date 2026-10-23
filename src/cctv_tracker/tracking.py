"""Configuration for the pinned ByteTrack adapter; durations remain in sessions."""
from dataclasses import dataclass
import math


@dataclass(frozen=True)
class TrackingRules:
    activation_threshold: float = 0.25
    matching_threshold: float = 0.8
    lost_buffer_seconds: float = 1.0
    confirmation_frames: int = 1
    max_prediction_steps: int = 30

    def __post_init__(self):
        for name in ('activation_threshold', 'matching_threshold'):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 < value < 1:
                raise ValueError(f'{name} must be finite and in (0,1)')
        if self.activation_threshold >= .9:
            raise ValueError('Activation threshold must leave room for ByteTrack new-track threshold')
        value = self.lost_buffer_seconds
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 < value <= 30:
            raise ValueError('lost_buffer_seconds must be in (0,30]')
        for name, high in (('confirmation_frames', 30), ('max_prediction_steps', 120)):
            value = getattr(self, name)
            if type(value) is not int or not 1 <= value <= high:
                raise ValueError(f'{name} must be an integer in [1,{high}]')
