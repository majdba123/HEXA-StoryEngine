"""Reference grammar G5 for authored arrow/path artwork: it writes on along its relation.

The Final Package draws its relations as artwork (an arrow or path asset between two
objects). In the approved references such an arrow is never faded in place: it is drawn
from the cause toward the effect, then held. This module only decides *whether* and *in
which direction* an existing authored asset is revealed that way:

* the asset must be named as an arrow/path by the package's own semantics (never by
  pixels), and must not be a character;
* the direction comes from an authored Story relation whose two participants are both on
  screen and between which the path lies; without one the asset keeps its normal reveal;
* the artwork itself must span that direction (its alpha is elongated along it): a round
  badge or a circular icon is not a path and is never wiped sideways (icons cascade, G7);
* the write-on is Motion's own entry window (Story reveal -> settle), never longer than
  the reference's ~8 frames, and abstains when that window is under 3 frames. It ends on
  the asset's exact authored alpha, so nothing about the settled scene changes.
"""

from __future__ import annotations

from functools import lru_cache
from math import sqrt
from pathlib import Path

import numpy as np
from PIL import Image

from app.models import StoryBeat

PATH_TERMS = ("arrow", "path", "route", "سهم", "مسار")
MIN_FRAMES = 3
MAX_FRAMES = 8
# Soft leading edge of the reveal, as a share of the path's length along its direction.
_EDGE = 0.12
_ALPHA_FLOOR = 10
# Alpha spread along the direction / across it. Measured on the corpus: spanning arrows
# 2.6, round badges and circular icons 0.9-1.0, small path fragments 1.1.
MIN_ELONGATION = 1.6
_SHAPE_SIDE = 256


def _is_path(entity) -> bool:
    if str(entity.role or "").upper() == "CHARACTER":
        return False
    metadata = entity.package_metadata or {}
    text = " ".join(
        str(value or "") for value in (
            entity.semantic_name, metadata.get("semantic_name"), metadata.get("visual_concept"),
        )
    ).lower()
    return any(term in text for term in PATH_TERMS)


def elongation(image_path: Path, direction: tuple[float, float]) -> float:
    """Alpha-weighted spread of the artwork along ``direction`` over its spread across it."""
    with Image.open(image_path) as opened:
        rgba = opened.convert("RGBA")
        rgba.thumbnail((_SHAPE_SIDE, _SHAPE_SIDE))
        alpha = np.asarray(rgba.getchannel("A"), dtype=float) / 255.0
    ys, xs = np.nonzero(alpha >= _ALPHA_FLOOR / 255.0)
    if xs.size < 2:
        return 0.0
    weights = alpha[ys, xs]
    dx, dy = direction

    def spread(values: np.ndarray) -> float:
        mean = np.average(values, weights=weights)
        return float(np.sqrt(np.average((values - mean) ** 2, weights=weights)))

    return spread(xs * dx + ys * dy) / max(1e-6, spread(ys * dx - xs * dy))


def authored_path_directions(
    beat: StoryBeat, centers: dict[str, tuple[float, float]],
    parent_of: dict[str, str | None] | None = None,
    images: dict[str, Path] | None = None,
) -> dict[str, tuple[float, float]]:
    """Unit direction (frame pixels) for every on-screen authored path asset that lies
    between the two on-screen participants of an authored causal relation.

    Only the package's causal asset relations give a direction; its declared narration
    order (``DECLARED_PROGRESSION``) is sequence, not flow. A piece of another object's
    family (``parent_of``) never writes on as a path."""
    context = beat.semantic_context
    if context is None:
        return {}
    parent_of = parent_of or {}
    entities = {entity.unit_id: entity for entity in context.entities}
    unit_of = {
        row.asset_id: row.semantic_unit_id
        for row in beat.asset_activations
        if row.semantic_unit_id and row.asset_id in centers
    }
    asset_of: dict[str, str] = {}
    for asset_id, unit_id in sorted(unit_of.items()):
        if not parent_of.get(asset_id):
            asset_of.setdefault(unit_id, asset_id)
    directions: dict[str, tuple[float, float]] = {}
    for asset_id, unit_id in sorted(unit_of.items()):
        entity = entities.get(unit_id)
        if entity is None or not _is_path(entity):
            continue
        parent = parent_of.get(asset_id)
        if parent and unit_of.get(parent) != unit_id:
            continue
        px, py = centers[asset_id]
        best: tuple[float, float, float] | None = None
        for relation in context.relations:
            if not relation.causal or unit_id in (relation.source_unit_id, relation.target_unit_id):
                continue
            source = asset_of.get(relation.source_unit_id)
            target = asset_of.get(relation.target_unit_id)
            if source is None or target is None or len({source, target, asset_id}) < 3:
                continue
            (sx, sy), (tx, ty) = centers[source], centers[target]
            vx, vy = tx - sx, ty - sy
            length = sqrt(vx * vx + vy * vy)
            if length <= 1e-6:
                continue
            along = ((px - sx) * vx + (py - sy) * vy) / (length * length)
            if not 0.0 <= along <= 1.0:
                continue  # the path is not between this relation's participants
            off_line = abs((px - sx) * vy - (py - sy) * vx) / length
            if best is None or off_line < best[0]:
                best = (off_line, vx / length, vy / length)
        if best is None:
            continue
        direction = (best[1], best[2])
        image = (images or {}).get(asset_id)
        if image is None or elongation(image, direction) < MIN_ELONGATION:
            continue  # not a path spanning the relation (badge, icon, fragment, unknown)
        directions[asset_id] = direction
    return directions


def write_on_frame_count(first_frame: int, settle_frame: int) -> int:
    """Frames of the write-on inside Motion's entry window, or 0 to abstain."""
    frames = min(MAX_FRAMES, settle_frame - first_frame)
    return frames if frames >= MIN_FRAMES else 0


@lru_cache(maxsize=256)
def _alpha_extent(path: str) -> tuple[int, int, tuple[int, int, int, int] | None]:
    with Image.open(path) as opened:
        rgba = opened.convert("RGBA")
        bbox = rgba.getchannel("A").point(
            lambda value: 255 if value >= _ALPHA_FLOOR else 0).getbbox()
        return rgba.width, rgba.height, bbox


def write_on_filter(
    *, image_path: Path, box: tuple[int, int], direction: tuple[float, float],
    first_frame: int, frames: int,
) -> str:
    """A ``geq`` alpha mask over the box-sized, aspect-fitted asset stream.

    Frame ``first_frame`` shows the first eased step; frame ``first_frame + frames - 1``
    and every later frame carry the asset's exact authored alpha (the mask saturates)."""
    width, height, bbox = _alpha_extent(str(image_path))
    box_w, box_h = box
    k = min(box_w / max(1, width), box_h / max(1, height))
    ox, oy = (box_w - width * k) / 2.0, (box_h - height * k) / 2.0
    left, top, right, bottom = bbox if bbox is not None else (0, 0, width, height)
    corners = [(ox + x * k, oy + y * k) for x in (left, right) for y in (top, bottom)]
    dx, dy = direction
    projections = [x * dx + y * dy for x, y in corners]
    low, span = min(projections), max(1e-6, max(projections) - min(projections))
    progress = f"(1-pow(1-clip((N-{first_frame - 1})/{frames},0,1),3))"
    along = f"((X*{dx:.6f}+Y*{dy:.6f}-{low:.3f})/{span:.3f})"
    mask = f"clip(({progress}*{1 + _EDGE:.3f}-{along})/{_EDGE:.3f},0,1)"
    return f",geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='alpha(X,Y)*{mask}'"
