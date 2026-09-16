from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from app.models import LayoutItem, VisualAsset


Box = tuple[float, float, float, float]


@dataclass(frozen=True, slots=True)
class AssetFootprint:
    """Approximate the actual visible alpha footprint inside a composed layout box."""

    box: Box
    coverage: float


class AlphaFootprintResolver:
    """Resolve visible artwork footprints from the cutout alpha, not just layout boxes.

    Pass2 assets intentionally preserve full-canvas geometry so separated pieces can be
    reassembled exactly. Their LayoutItem therefore describes the authored canvas slot,
    while the visible pixels can occupy only a small part of that slot. Text placement
    must reason about the visible alpha, otherwise it either wastes whitespace or covers
    a real object despite thinking the generic layout box is safe.
    """

    _MIN_ALPHA = 10

    def __init__(self) -> None:
        self._cache: dict[Path, tuple[float, float, float, float] | None] = {}

    def resolve(self, item: LayoutItem, asset: VisualAsset | None) -> AssetFootprint:
        fallback = self._layout_box(item)
        if asset is None or not asset.image_path.is_file():
            return AssetFootprint(box=fallback, coverage=1.0)

        normalized = self._normalized_alpha_bbox(asset.image_path)
        if normalized is None:
            return AssetFootprint(box=fallback, coverage=1.0)

        ax0, ay0, ax1, ay1 = normalized
        left = item.x - item.width / 2
        top = item.y - item.height / 2
        box = (
            left + item.width * ax0,
            top + item.height * ay0,
            left + item.width * ax1,
            top + item.height * ay1,
        )
        coverage = max(0.0, min(1.0, (ax1 - ax0) * (ay1 - ay0)))
        return AssetFootprint(box=box, coverage=coverage)

    def _normalized_alpha_bbox(self, path: Path) -> tuple[float, float, float, float] | None:
        cached = self._cache.get(path)
        if path in self._cache:
            return cached
        try:
            with Image.open(path) as opened:
                rgba = opened.convert("RGBA")
                alpha = rgba.getchannel("A")
                # Ignore near-zero antialias noise when estimating occupancy. The real
                # renderer still keeps those pixels; the text director adds a protected
                # halo around the resulting footprint.
                binary = alpha.point(lambda value: 255 if value >= self._MIN_ALPHA else 0)
                bbox = binary.getbbox()
                if bbox is None:
                    result = None
                else:
                    width, height = rgba.size
                    x0, y0, x1, y1 = bbox
                    result = (
                        x0 / max(1, width),
                        y0 / max(1, height),
                        x1 / max(1, width),
                        y1 / max(1, height),
                    )
        except (OSError, ValueError):
            result = None
        self._cache[path] = result
        return result

    @staticmethod
    def _layout_box(item: LayoutItem) -> Box:
        return (
            item.x - item.width / 2,
            item.y - item.height / 2,
            item.x + item.width / 2,
            item.y + item.height / 2,
        )
