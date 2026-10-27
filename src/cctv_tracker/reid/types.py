from dataclasses import dataclass, field
import math


@dataclass(frozen=True)
class FrameToken:
    camera_id: str
    run_id: str
    generation_id: str
    frame_seq: int
    monotonic_ns: int
    mapping_version: int

    def __post_init__(self):
        if any(not isinstance(v, str) or not v for v in self.scope):
            raise ValueError('Incomplete ReID frame scope')
        if any(type(v) is not int or v < 0 for v in (self.frame_seq, self.monotonic_ns, self.mapping_version)) or self.frame_seq < 1:
            raise ValueError('Invalid ReID frame clock/version')

    @property
    def scope(self):
        return self.camera_id, self.run_id, self.generation_id


@dataclass(frozen=True)
class ModelIdentity:
    model_id: str
    sha256: str
    preprocessing: str
    dimensions: int

    def __post_init__(self):
        if (not isinstance(self.model_id, str) or not self.model_id.strip()
                or not isinstance(self.preprocessing, str) or not self.preprocessing.strip()
                or not isinstance(self.sha256, str) or len(self.sha256) != 64 or any(c not in '0123456789abcdef' for c in self.sha256)):
            raise ValueError('Invalid ReID model identity')
        if type(self.dimensions) is not int or not 1 <= self.dimensions <= 4096:
            raise ValueError('Invalid embedding dimension')


@dataclass(frozen=True)
class SampleRef:
    token: FrameToken
    detection_index: int
    box: tuple[float, float, float, float]
    blur_score: float
    confidence: float

    def __post_init__(self):
        object.__setattr__(self, 'box', tuple(self.box))
        if type(self.detection_index) is not int or self.detection_index < 0:
            raise ValueError('Invalid ReID detection index')
        if (len(self.box) != 4 or any(not math.isfinite(v) or not 0 <= v <= 1 for v in self.box)
                or self.box[0] >= self.box[2] or self.box[1] >= self.box[3]):
            raise ValueError('Invalid ReID sample box')
        if not math.isfinite(self.blur_score) or self.blur_score < 0 or not math.isfinite(self.confidence) or not 0 <= self.confidence <= 1:
            raise ValueError('Invalid ReID sample quality')


@dataclass(frozen=True)
class AppearanceSample:
    ref: SampleRef
    image: object = field(repr=False, compare=False)


@dataclass(frozen=True)
class EmbeddingResult:
    sample: SampleRef
    model: ModelIdentity
    vector: tuple[float, ...] = field(repr=False)

    def __post_init__(self):
        object.__setattr__(self, 'vector', tuple(self.vector))
        if len(self.vector) != self.model.dimensions or any(not math.isfinite(v) for v in self.vector):
            raise ValueError('Invalid ReID embedding output')
        if not math.isclose(sum(v*v for v in self.vector), 1, abs_tol=1e-4):
            raise ValueError('ReID embedding must be L2 normalized')


@dataclass(frozen=True)
class MatchDecision:
    token: FrameToken
    detection_index: int
    candidate_session_id: str
    target_session_id: str | None
    action: str
    reason: str
    score: float | None = None
    margin: float | None = None
    policy_revision: str = 'reid-shadow-v1'
