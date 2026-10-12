import math


def _cross(a, b, c):
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _intersects(a, b, c, d):
    crosses = (_cross(a, b, c), _cross(a, b, d), _cross(c, d, a), _cross(c, d, b))
    if crosses[0] * crosses[1] < 0 and crosses[2] * crosses[3] < 0:
        return True
    for p, q, r, cross in ((a, b, c, crosses[0]), (a, b, d, crosses[1]), (c, d, a, crosses[2]), (c, d, b, crosses[3])):
        if abs(cross) < 1e-12 and min(p[0], q[0]) <= r[0] <= max(p[0], q[0]) and min(p[1], q[1]) <= r[1] <= max(p[1], q[1]):
            return True
    return False


def area(poly):
    return abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(poly, poly[1:] + poly[:1]))) / 2


def valid_polygon(poly):
    if not 3 <= len(poly) <= 64 or len(set(poly)) != len(poly):
        return False
    if any(len(p) != 2 or any(not math.isfinite(v) or not 0 <= v <= 1 for v in p) for p in poly):
        return False
    n = len(poly)
    for i in range(n):
        for j in range(i + 1, n):
            if j == i + 1 or (i == 0 and j == n - 1):
                continue
            if _intersects(poly[i], poly[(i + 1) % n], poly[j], poly[(j + 1) % n]):
                return False
    return area(poly) > 1e-8


def overlap_ratio(box, polygon):
    """Polygon clipped to detection rectangle; supports simple concave polygons."""
    x1, y1, x2, y2 = box
    denominator = (x2 - x1) * (y2 - y1)
    if denominator <= 0:
        return 0.0
    vertices = list(polygon)
    for axis, boundary, keep_greater in ((0, x1, True), (0, x2, False), (1, y1, True), (1, y2, False)):
        if not vertices:
            return 0.0
        output = []
        prev = vertices[-1]
        inside = lambda p: p[axis] >= boundary if keep_greater else p[axis] <= boundary
        for current in vertices:
            if inside(prev) != inside(current):
                ratio = (boundary - prev[axis]) / (current[axis] - prev[axis])
                output.append(tuple(prev[k] + ratio * (current[k] - prev[k]) for k in (0, 1)))
            if inside(current):
                output.append(current)
            prev = current
        vertices = output
    return min(1.0, area(vertices) / denominator) if len(vertices) >= 3 else 0.0
