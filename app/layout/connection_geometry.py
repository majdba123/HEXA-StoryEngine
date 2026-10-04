from __future__ import annotations

from math import hypot

Rect = tuple[float, float, float, float]  # left, top, right, bottom in pixels

GAP_PX = 14.0
MIN_LENGTH_PX = 70.0


def center(rect: Rect) -> tuple[float, float]:
    return (rect[0] + rect[2]) / 2.0, (rect[1] + rect[3]) / 2.0


def exit_point(rect: Rect, origin: tuple[float, float], direction: tuple[float, float]):
    """Where a ray from the rect centre leaves the rect, pushed out by the gap."""
    half_w, half_h = (rect[2] - rect[0]) / 2.0, (rect[3] - rect[1]) / 2.0
    dx, dy = direction
    scale = min(
        half_w / abs(dx) if abs(dx) > 1e-9 else float("inf"),
        half_h / abs(dy) if abs(dy) > 1e-9 else float("inf"),
    )
    return origin[0] + dx * (scale + GAP_PX), origin[1] + dy * (scale + GAP_PX)


def connector_endpoints(source: Rect, target: Rect, others: list[Rect]):
    """Arrow endpoints between two boxes, or None when too short, inverted or crossing."""
    sx, sy = center(source)
    tx, ty = center(target)
    length = hypot(tx - sx, ty - sy)
    if length < 1e-6:
        return None
    ux, uy = (tx - sx) / length, (ty - sy) / length
    p0 = exit_point(source, (sx, sy), (ux, uy))
    p1 = exit_point(target, (tx, ty), (-ux, -uy))
    if hypot(p1[0] - p0[0], p1[1] - p0[1]) < MIN_LENGTH_PX:
        return None
    # The segment must leave source and enter target in order (no overlap inversion).
    if (p1[0] - p0[0]) * ux + (p1[1] - p0[1]) * uy <= 0.0:
        return None
    for rect in others:
        if segment_hits_rect(p0, p1, rect):
            return None
    return p0, p1


def segment_hits_rect(p0, p1, rect: Rect) -> bool:
    """Liang-Barsky segment/rectangle intersection."""
    left, top, right, bottom = rect
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    t0, t1 = 0.0, 1.0
    for p, q in ((-dx, p0[0] - left), (dx, right - p0[0]),
                 (-dy, p0[1] - top), (dy, bottom - p0[1])):
        if abs(p) < 1e-12:
            if q < 0:
                return False
            continue
        t = q / p
        if p < 0:
            if t > t1:
                return False
            t0 = max(t0, t)
        else:
            if t < t0:
                return False
            t1 = min(t1, t)
    return t0 <= t1
