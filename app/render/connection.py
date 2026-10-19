from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from math import atan2, cos, hypot, sin
from pathlib import Path

from PIL import Image, ImageDraw

from app.layout.connection_geometry import Rect, segment_hits_rect
from app.layout.connection_geometry import connector_endpoints as _endpoints
from app.models import MotionCue, StoryBeat

_MIN_VISIBLE_SECONDS = 0.25
_LINE_PX = 11  # reference arrows: a bold hand-drawn black stroke
_HEAD_LENGTH_PX = 40.0
_HEAD_HALF_WIDTH_PX = 20.0
_INK = (22, 22, 24, 255)
_SUPERSAMPLE = 2
# Reference grammar G5 (docs/reference-motion-grammar.md): the arrow writes on from the
# cause toward the effect over ~8 frames; its head appears as the stroke arrives.
WRITE_ON_FRAMES = 8
_HEAD_AT = 0.85
_FPS_HINT = 30
# Reference grammar G17: almost every keyword in the references is tied to the thing it
# names by a short, curved, hand-drawn black arrow that is drawn with the word and leaves
# with it. Bows are fractions of the chord, curved first (the reference arrows are
# curved); a straight path is the last resort.
LABEL_BOWS = (0.22, -0.22, 0.34, -0.34, 0.0)
LABEL_MAX_LENGTH = 0.42      # share of the frame width: a longer arrow would cross the scene
LABEL_MIN_SECONDS = 0.4      # an arrow must be readable, never a flash
LABEL_MIN_LENGTH_PX = 90.0   # shorter reads as a mark, not an arrow (reference px at 1080p)
_LABEL_GAP_PX = 10.0
_CURVE_SAMPLES = 32
_FRAME_MARGIN_PX = 8.0
_ALPHA_FLOOR = 10


@dataclass(frozen=True, slots=True)
class ConnectionSpec:
    """One drawn arrow: an authored relation, or a keyword pointing at what it names."""

    start: float  # beat-local seconds
    end: float
    p0: tuple[float, float]
    p1: tuple[float, float]
    control: tuple[float, float] | None = None  # quadratic bezier bow; None = straight


@dataclass(frozen=True, slots=True)
class LabelAnchor:
    """A placed keyword and the asset it names (output pixels, absolute seconds)."""

    asset_id: str
    box: Rect
    start: float
    end: float


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


def label_arrow_specs(
    *,
    labels: list[LabelAnchor],
    visible: dict[str, Rect],
    revealed: dict[str, float],
    family: dict[str, str],
    segment_start: float,
    duration: float,
    frame: tuple[int, int],
    spatial_scale: float = 1.0,
) -> list[ConnectionSpec]:
    """Arrows from each placed keyword to the visible artwork it names (G17).

    ``visible`` holds each asset's drawn artwork (output pixels), ``revealed`` its first
    visible instant (absolute seconds), ``family`` its Pass2 family. An arrow starts when
    both the word and its asset are on screen, ends with the word, and is drawn only when
    a clean curved (or straight) path exists: clear of every other artwork and keyword,
    inside the frame, between the connector's minimum length and LABEL_MAX_LENGTH.
    """
    specs: list[ConnectionSpec] = []
    for label in labels:
        target = visible.get(label.asset_id)
        if target is None or label.asset_id not in revealed:
            continue
        start = max(label.start, revealed[label.asset_id]) - segment_start
        end = min(duration, label.end - segment_start)
        if start < 0.0 or end - start < LABEL_MIN_SECONDS:
            continue
        own = family.get(label.asset_id, label.asset_id)
        others = [rect for asset_id, rect in visible.items()
                  if family.get(asset_id, asset_id) != own]
        others += [row.box for row in labels if row is not label]
        route = _label_route(label.box, target, others, spatial_scale=spatial_scale, frame=frame)
        if route is None:
            continue
        p0, p1, control = route
        specs.append(ConnectionSpec(start=start, end=end, p0=p0, p1=p1, control=control))
    return specs


def _label_route(source: Rect, target: Rect, others: list[Rect], *, spatial_scale: float,
                 frame: tuple[int, int]):
    if _overlaps(source, target, _LABEL_GAP_PX * spatial_scale):
        return None  # the word already touches what it names
    straight = _endpoints(source, target, [], spatial_scale=spatial_scale)
    if straight is None:
        return None
    (x0, y0), (x1, y1) = straight
    length = hypot(x1 - x0, y1 - y0)
    if length > LABEL_MAX_LENGTH * frame[0] or length < LABEL_MIN_LENGTH_PX * spatial_scale:
        return None
    nx, ny = -(y1 - y0) / length, (x1 - x0) / length
    mx, my = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    for bow in LABEL_BOWS:
        control = None if bow == 0.0 else (mx + nx * bow * length, my + ny * bow * length)
        path = [straight[0], straight[1]] if control is None else _bezier(straight[0], control, straight[1])
        if _path_clear(path, source=source, target=target, others=others, frame=frame):
            return straight[0], straight[1], control
    return None


def _path_clear(path, *, source: Rect, target: Rect, others: list[Rect], frame: tuple[int, int]) -> bool:
    pairs = list(zip(path, path[1:]))
    if any(segment_hits_rect(a, b, rect) for rect in others for a, b in pairs):
        return False
    if any(_inside(point, source) or _inside(point, target) for point in path[1:-1]):
        return False
    return all(_FRAME_MARGIN_PX <= x <= frame[0] - _FRAME_MARGIN_PX
               and _FRAME_MARGIN_PX <= y <= frame[1] - _FRAME_MARGIN_PX for x, y in path)


def _overlaps(a: Rect, b: Rect, margin: float) -> bool:
    return not (a[2] + margin <= b[0] or b[2] + margin <= a[0]
                or a[3] + margin <= b[1] or b[3] + margin <= a[1])


def _bezier(p0, control, p1, samples: int = _CURVE_SAMPLES) -> list[tuple[float, float]]:
    points = []
    for index in range(samples + 1):
        t = index / samples
        a, b, c = (1 - t) ** 2, 2 * (1 - t) * t, t * t
        points.append((a * p0[0] + b * control[0] + c * p1[0],
                       a * p0[1] + b * control[1] + c * p1[1]))
    return points


def _inside(point: tuple[float, float], rect: Rect) -> bool:
    return rect[0] < point[0] < rect[2] and rect[1] < point[1] < rect[3]


@lru_cache(maxsize=512)
def _alpha_extent(path: str) -> tuple[int, int, tuple[int, int, int, int] | None]:
    with Image.open(path) as opened:
        rgba = opened.convert("RGBA")
        bbox = rgba.getchannel("A").point(
            lambda value: 255 if value >= _ALPHA_FLOOR else 0).getbbox()
        return rgba.width, rgba.height, bbox


def visible_rect(box: Rect, image_path: Path) -> Rect:
    """The artwork the viewer actually sees inside a layout box (aspect fit + alpha)."""
    try:
        width, height, bbox = _alpha_extent(str(image_path))
    except (OSError, ValueError):
        return box
    if bbox is None:
        return box
    left, top, right, bottom = box
    k = min((right - left) / max(1, width), (bottom - top) / max(1, height))
    ox = left + ((right - left) - width * k) / 2.0
    oy = top + ((bottom - top) - height * k) / 2.0
    return (ox + bbox[0] * k, oy + bbox[1] * k, ox + bbox[2] * k, oy + bbox[3] * k)


def draw_connection(spec: ConnectionSpec, size: tuple[int, int], path: Path, *,
                    spatial_scale: float = 1.0, progress: float = 1.0) -> Path:
    """Write one transparent full-frame PNG holding the arrow (supersampled for AA).

    ``progress`` < 1 draws the stroke only part of the way from the source; the head
    grows out of it once the stroke arrives (write-on, reference grammar G5). At 1.0 the
    drawing is exactly the complete arrow."""
    scale = _SUPERSAMPLE
    canvas = Image.new("RGBA", (size[0] * scale, size[1] * scale), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    x1, y1 = spec.p1
    head_length = _HEAD_LENGTH_PX * spatial_scale
    if spec.control is None:
        angle = atan2(y1 - spec.p0[1], x1 - spec.p0[0])
        base = (x1 - cos(angle) * head_length, y1 - sin(angle) * head_length)
        stroke = [spec.p0, base]
    else:
        # The stroke ends where the head begins: the last curve point a head-length short.
        curve = _bezier(spec.p0, spec.control, spec.p1)
        cut = len(curve) - 1
        while cut > 1 and hypot(x1 - curve[cut - 1][0], y1 - curve[cut - 1][1]) < head_length:
            cut -= 1
        stroke = curve[:cut]
        base = stroke[-1]
        angle = atan2(y1 - base[1], x1 - base[0])
    progress = max(0.0, min(1.0, progress))
    reach = min(1.0, progress / _HEAD_AT)
    lengths = [hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(stroke, stroke[1:])]
    remaining = sum(lengths) * reach
    drawn = [stroke[0]]
    for (a, b), piece in zip(zip(stroke, stroke[1:]), lengths):
        if remaining <= 0.0:
            break
        share = 1.0 if piece <= remaining or piece <= 1e-9 else remaining / piece
        drawn.append((a[0] + (b[0] - a[0]) * share, a[1] + (b[1] - a[1]) * share))
        remaining -= piece
    width = max(1, round(_LINE_PX * spatial_scale * scale))
    for a, b in zip(drawn, drawn[1:]):
        draw.line([(a[0] * scale, a[1] * scale), (b[0] * scale, b[1] * scale)],
                  fill=_INK, width=width)
    for cx, cy in drawn:
        radius = _LINE_PX * spatial_scale * scale / 2.0
        draw.ellipse(
            [cx * scale - radius, cy * scale - radius, cx * scale + radius, cy * scale + radius],
            fill=_INK,
        )
    if progress >= _HEAD_AT:
        grow = max(0.35, min(1.0, (progress - _HEAD_AT) / (1.0 - _HEAD_AT)))
        length = head_length * grow
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
