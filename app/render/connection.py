from __future__ import annotations

from dataclasses import dataclass
from math import atan2, cos, sin
from pathlib import Path

from PIL import Image, ImageDraw

from app.layout.connection_geometry import Rect
from app.layout.connection_geometry import connector_endpoints as _endpoints
from app.models import MotionCue, StoryBeat

_MIN_VISIBLE_SECONDS = 0.25
_FADE_SECONDS = 0.20
_LINE_PX = 7
_HEAD_LENGTH_PX = 30.0
_HEAD_HALF_WIDTH_PX = 14.0
_INK = (31, 41, 55, 255)
_SUPERSAMPLE = 2


@dataclass(frozen=True, slots=True)
class ConnectionSpec:
    """One authored directional relation, drawn between two Composition boxes."""

    start: float  # beat-local seconds
    end: float
    p0: tuple[float, float]
    p1: tuple[float, float]


def connection_specs(
    *,
    beat: StoryBeat,
    items: dict[str, Rect],
    cues: dict[str, MotionCue],
    segment_start: float,
    duration: float,
) -> list[ConnectionSpec]:
    """Plan visible connections from Motion segments that carry an authored relation.

    Geometry is derived from Composition boxes only; nothing here places an asset. A
    connection abstains when either end is not on screen, the visible gap is too short,
    the line would cross a third element, or too little time remains to read it.
    """
    specs: list[ConnectionSpec] = []
    seen: set[tuple[str, str]] = set()
    for cue in sorted(cues.values(), key=lambda row: row.asset_id):
        for segment in sorted(cue.segments, key=lambda row: (row.start, row.end)):
            if not segment.connection or segment.phase != "INTERACT":
                continue
            source_id, target_id = segment.source_asset_id, segment.target_asset_id
            if (
                not source_id or not target_id
                or source_id not in items or target_id not in items
                or (source_id, target_id) in seen
            ):
                continue
            source_cue, target_cue = cues.get(source_id), cues.get(target_id)
            if source_cue is None or target_cue is None:
                continue
            start = max(
                float(segment.start), float(source_cue.start), float(target_cue.start),
            ) - segment_start
            start = max(0.0, start)
            end = duration
            if end - start < _MIN_VISIBLE_SECONDS:
                continue
            others = [
                rect for asset_id, rect in items.items()
                if asset_id not in {source_id, target_id}
            ]
            points = _endpoints(items[source_id], items[target_id], others)
            if points is None:
                continue
            seen.add((source_id, target_id))
            specs.append(ConnectionSpec(start=start, end=end, p0=points[0], p1=points[1]))
    return specs


def draw_connection(spec: ConnectionSpec, size: tuple[int, int], path: Path) -> Path:
    """Write one transparent full-frame PNG holding the arrow (supersampled for AA)."""
    scale = _SUPERSAMPLE
    canvas = Image.new("RGBA", (size[0] * scale, size[1] * scale), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    (x0, y0), (x1, y1) = spec.p0, spec.p1
    angle = atan2(y1 - y0, x1 - x0)
    base = (x1 - cos(angle) * _HEAD_LENGTH_PX, y1 - sin(angle) * _HEAD_LENGTH_PX)
    draw.line(
        [(x0 * scale, y0 * scale), (base[0] * scale, base[1] * scale)],
        fill=_INK, width=_LINE_PX * scale,
    )
    for cx, cy in ((x0, y0), base):
        radius = _LINE_PX * scale / 2.0
        draw.ellipse(
            [cx * scale - radius, cy * scale - radius, cx * scale + radius, cy * scale + radius],
            fill=_INK,
        )
    nx, ny = -sin(angle), cos(angle)
    head = [
        (x1 * scale, y1 * scale),
        ((base[0] + nx * _HEAD_HALF_WIDTH_PX) * scale, (base[1] + ny * _HEAD_HALF_WIDTH_PX) * scale),
        ((base[0] - nx * _HEAD_HALF_WIDTH_PX) * scale, (base[1] - ny * _HEAD_HALF_WIDTH_PX) * scale),
    ]
    draw.polygon(head, fill=_INK)
    path.parent.mkdir(parents=True, exist_ok=True)
    canvas.resize(size, Image.LANCZOS).save(path)
    return path


def fade_seconds(spec: ConnectionSpec) -> float:
    return min(_FADE_SECONDS, max(0.05, spec.end - spec.start))
