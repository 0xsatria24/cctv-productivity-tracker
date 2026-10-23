"""Measured-box anchors and a bounded mapping onto one rectangular floor plane."""
from dataclasses import dataclass
from functools import lru_cache
import math

from .domain.geometry import area, valid_polygon


def edge_distance(point, polygon):
    x, y = point
    distances = []
    for (ax, ay), (bx, by) in zip(polygon, polygon[1:] + polygon[:1]):
        dx, dy = bx - ax, by - ay
        t = max(0, min(1, ((x - ax) * dx + (y - ay) * dy) / (dx * dx + dy * dy)))
        distances.append(math.hypot(x - ax - t * dx, y - ay - t * dy))
    return min(distances)


def contains(point, polygon):
    if edge_distance(point, polygon) <= 1e-9:
        return True
    x, y = point
    inside = False
    for (ax, ay), (bx, by) in zip(polygon, polygon[1:] + polygon[:1]):
        if (ay > y) != (by > y) and x < ax + (y - ay) * (bx - ax) / (by - ay):
            inside = not inside
    return inside


@dataclass(frozen=True)
class PositionCalibration:
    mode: str = 'bbox_overlap'
    image_points: tuple[tuple[float, float], ...] = ()
    floor_width_m: float | None = None
    floor_depth_m: float | None = None
    image_boundary_margin: float = 0.01
    floor_boundary_margin_m: float = 0.1

    def __post_init__(self):
        if self.mode not in {'bbox_overlap', 'footpoint', 'homography'}:
            raise ValueError('Metode posisi tidak dikenal')
        for value, maximum in ((self.image_boundary_margin, 0.1), (self.floor_boundary_margin_m, 5)):
            if not math.isfinite(value) or not 0 < value <= maximum:
                raise ValueError('Toleransi batas posisi tidak valid')
        if self.mode != 'homography':
            if self.image_points or self.floor_width_m is not None or self.floor_depth_m is not None:
                raise ValueError('Referensi lantai hanya berlaku untuk homography')
            return
        p = self.image_points
        if len(p) != 4 or not valid_polygon(p) or area(p) < 0.001:
            raise ValueError('Pilih empat sudut lantai berurutan dengan area yang cukup')
        turns = [(p[(i + 1) % 4][0] - p[i][0]) * (p[(i + 2) % 4][1] - p[(i + 1) % 4][1])
                 - (p[(i + 1) % 4][1] - p[i][1]) * (p[(i + 2) % 4][0] - p[(i + 1) % 4][0]) for i in range(4)]
        if not (all(t > 1e-5 for t in turns) or all(t < -1e-5 for t in turns)):
            raise ValueError('Empat sudut lantai harus membentuk segiempat cembung')
        for value in (self.floor_width_m, self.floor_depth_m):
            if value is None or not math.isfinite(value) or not 0.1 <= value <= 1000:
                raise ValueError('Isi ukuran lantai nyata antara 0.1 dan 1000 meter')
        if self.floor_boundary_margin_m >= min(self.floor_width_m, self.floor_depth_m) / 2:
            raise ValueError('Toleransi batas terlalu besar untuk ukuran lantai')
        matrix(self)

    def validate_zones(self, zones):
        if self.mode == 'homography' and any(not contains(p, self.image_points) for z in zones for p in z.polygon):
            raise ValueError('Semua titik zona harus berada di dalam empat sudut lantai')


def position_calibration(value=None):
    raw = dict(value or {})
    raw['image_points'] = tuple(tuple(p) for p in raw.get('image_points', ()))
    return PositionCalibration(**raw)


@lru_cache(maxsize=64)
def matrix(calibration):
    # Four exact correspondences: image corners -> measured rectangle in meters.
    target = ((0, 0), (calibration.floor_width_m, 0),
              (calibration.floor_width_m, calibration.floor_depth_m), (0, calibration.floor_depth_m))
    rows = []
    for (x, y), (u, v) in zip(calibration.image_points, target):
        rows.extend(([x, y, 1, 0, 0, 0, -u*x, -u*y, u],
                     [0, 0, 0, x, y, 1, -v*x, -v*y, v]))
    for column in range(8):
        pivot = max(range(column, 8), key=lambda i: abs(rows[i][column]))
        rows[column], rows[pivot] = rows[pivot], rows[column]
        scale = rows[column][column]
        if abs(scale) < 1e-10:
            raise ValueError('Referensi lantai tidak stabil; pilih ulang titik')
        rows[column] = [v / scale for v in rows[column]]
        for i in range(8):
            if i != column:
                factor = rows[i][column]
                rows[i] = [a - factor*b for a, b in zip(rows[i], rows[column])]
    h = tuple(row[8] for row in rows) + (1.,)
    denominators = [h[6]*x + h[7]*y + 1 for x, y in calibration.image_points]
    if min(denominators) <= 1e-8 <= max(denominators) or any(abs(d) < 1e-8 for d in denominators):
        raise ValueError('Proyeksi lantai melintasi horizon')
    return h


def project(point, calibration):
    if not contains(point, calibration.image_points):
        return None
    x, y = point
    h = matrix(calibration)
    denominator = h[6]*x + h[7]*y + h[8]
    return ((h[0]*x + h[1]*y + h[2]) / denominator,
            (h[3]*x + h[4]*y + h[5]) / denominator)


@lru_cache(maxsize=256)
def floor_polygon(polygon, calibration):
    return tuple(project(p, calibration) for p in polygon)


def measured_position(detection, calibration):
    x1, y1, x2, y2 = detection.box
    anchor = ((x1 + x2) / 2, y2)
    clipped = y2 >= 0.995
    floor = project(anchor, calibration) if calibration.mode == 'homography' and not clipped else None
    available = not clipped and (calibration.mode != 'homography' or floor is not None)
    return {'anchor': anchor, 'floor_m': floor, 'available': available,
            'reason': None if available else 'FEET_CLIPPED' if clipped else 'OUTSIDE_CALIBRATED_FLOOR',
            'method': 'bbox_bottom_center', 'estimated': True}
