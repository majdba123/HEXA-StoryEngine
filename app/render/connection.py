from __future__ import annotations

from dataclasses import dataclass
from math import atan2, cos, sin
from pathlib import Path

from PIL import Image, ImageDraw

from app.layout.connection_geometry import Rect
from app.layout.connection_geometry import connector_endpoints as _endpoints
from app.models import MotionCue, StoryBeat

_MIN_VISIBLE_SECONDS = 0.25
_LINE_PX = 7
_HEAD_LENGTH_PX = 30.0
_HEAD_HALF_WIDTH_PX = 14.0
_INK = (31, 41, 55, 255)
_SUPERSAMPLE = 2
# Reference grammar G5 (docs/reference-motion-grammar.md): the arrow writes on from the
# cause toward the effect over ~8 frames; its head appears as the stroke arrives.
WRITE_ON_FRAMES = 8
_HEAD_AT = 0.85
_FPS_HINT = 30


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
    spatial_scale: float = 1.0,
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
            points = _endpoints(items[source_id], items[target_id], others,
                                spatial_scale=spatial_scale)
            if points is None:
                continue
            seen.add((source_id, target_id))
            specs.append(ConnectionSpec(start=start, end=end, p0=points[0], p1=points[1]))
    return specs


def draw_connection(spec: ConnectionSpec, size: tuple[int, int], path: Path, *,
                    spatial_scale: float = 1.0, progress: float = 1.0) -> Path:
    """Write one transparent full-frame PNG holding the arrow (supersampled for AA).

    ``progress`` < 1 draws the stroke only part of the way from the source; the head
    grows out of it once the stroke arrives (write-on, reference grammar G5). At 1.0 the
    drawing is exactly the complete arrow."""
    scale = _SUPERSAMPLE
    canvas = Image.new("RGBA", (size[0] * scale, size[1] * scale), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    (x0, y0), (x1, y1) = spec.p0, spec.p1
    angle = atan2(y1 - y0, x1 - x0)
    base = (x1 - cos(angle) * _HEAD_LENGTH_PX * spatial_scale,
            y1 - sin(angle) * _HEAD_LENGTH_PX * spatial_scale)
    progress = max(0.0, min(1.0, progress))
    reach = min(1.0, progress / _HEAD_AT)
    tip = (x0 + (base[0] - x0) * reach, y0 + (base[1] - y0) * reach)
    draw.line(
        [(x0 * scale, y0 * scale), (tip[0] * scale, tip[1] * scale)],
        fill=_INK, width=max(1, round(_LINE_PX * spatial_scale * scale)),
    )
    for cx, cy in ((x0, y0), tip):
        radius = _LINE_PX * spatial_scale * scale / 2.0
        draw.ellipse(
            [cx * scale - radius, cy * scale - radius, cx * scale + radius, cy * scale + radius],
            fill=_INK,
        )
    if progress >= _HEAD_AT:
        grow = max(0.35, min(1.0, (progress - _HEAD_AT) / (1.0 - _HEAD_AT)))
        length = _HEAD_LENGTH_PX * spatial_scale * grow
        half = _HEAD_HALF_WIDTH_PX * spatial_scale * grow
        apex = (base[0] + cos(angle) * length, base[1] + sin(angle) * length)
        nx, ny = -sin(angle), cos(angle)
        head = [
            (apex[0] * scale, apex[1] * scale),
            ((base[0] + nx * half) * scale, (base[1] + ny * half) * scale),
            ((base[0] - nx * half) * scale, (base[1] - ny * half) * scale),
        ]
        draw.polygon(head, fill=_INK)
    path.parent.mkdir(parents=True, exist_ok=True)
    canvas.resize(size, Image.LANCZOS).save(path)
    return path


def write_on_frames(spec: ConnectionSpec, fps: int = _FPS_HINT) -> int:
    """Frames of the stroke write-on: the reference's ~8 (G5), never more than half of the
    connection's visible time, so the finished arrow is read longer than it is drawn."""
    visible_frames = int((spec.end - spec.start) * fps)
    return max(1, min(WRITE_ON_FRAMES, visible_frames // 2))


def draw_connection_sequence(spec: ConnectionSpec, size: tuple[int, int], stem: Path, *,
                             spatial_scale: float = 1.0, fps: int = _FPS_HINT) -> tuple[str, int]:
    """Write the write-on as numbered PNGs ``<stem>-NN.png`` (eased-out stroke growth).

    Returns the FFmpeg image2 pattern and the frame count; the renderer holds the last,
    complete frame for the rest of the connection's visible time."""
    frames = write_on_frames(spec, fps)
    for index in range(frames):
        linear = (index + 1) / frames
        eased = 1.0 - (1.0 - linear) ** 3  # fast start, settling arrival
        draw_connection(spec, size, stem.parent / f"{stem.name}-{index:02d}.png",
                        spatial_scale=spatial_scale, progress=eased)
    return str(stem.parent / f"{stem.name}-%02d.png"), frames
