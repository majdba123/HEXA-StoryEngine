from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

from app.models import LayoutItem, VisualAsset


Box = tuple[float, float, float, float]


@dataclass(frozen=True, slots=True)
class OccupancyStats:
    ratio: float
    occupied_pixels: int
    sample_pixels: int


class VisualOccupancyMap:
    """Low-resolution alpha occupancy for text/layout safety decisions.

    Final Package cutouts can have large rectangular bounding boxes while most pixels in
    those boxes are transparent. Text placement must reason about the pixels that are
    actually visible, otherwise valid negative space is incorrectly treated as occupied.
    This map mirrors the renderer's contain-fit of each cutout into its authored layout
    box and unions only meaningful alpha pixels on a deterministic analysis grid.
    """

    _MIN_ALPHA = 10

    def __init__(self, *, width: int = 320, height: int = 180) -> None:
        self.width = max(64, int(width))
        self.height = max(36, int(height))
        self._alpha_cache: dict[Path, np.ndarray | None] = {}

    def build(
        self,
        items: list[LayoutItem],
        assets_by_id: dict[str, VisualAsset],
    ) -> np.ndarray:
        canvas = np.zeros((self.height, self.width), dtype=np.bool_)
        for item in items:
            asset = assets_by_id.get(item.asset_id)
            if asset is None or not asset.image_path.is_file():
                self._fill_box(canvas, self._layout_box(item))
                continue
            alpha = self._alpha(asset.image_path)
            if alpha is None:
                self._fill_box(canvas, self._layout_box(item))
                continue
            self._composite_alpha(canvas, item, alpha)
        return canvas

    def overlap(self, occupancy: np.ndarray, box: Box) -> OccupancyStats:
        x0, y0, x1, y1 = self._pixel_box(box)
        if x1 <= x0 or y1 <= y0:
            return OccupancyStats(ratio=1.0, occupied_pixels=0, sample_pixels=0)
        region = occupancy[y0:y1, x0:x1]
        sample = int(region.size)
        occupied = int(np.count_nonzero(region))
        return OccupancyStats(
            ratio=occupied / max(1, sample),
            occupied_pixels=occupied,
            sample_pixels=sample,
        )

    def clearance(self, occupancy: np.ndarray, box: Box, *, max_ring: int = 18) -> float:
        """Return approximate normalized clearance to visible pixels around ``box``.

        The result is capped and intentionally coarse; it is a tie-breaker, never an
        authority capable of moving authored artwork.
        """
        x0, y0, x1, y1 = self._pixel_box(box)
        if x1 <= x0 or y1 <= y0:
            return 0.0
        for ring in range(1, max_ring + 1):
            rx0 = max(0, x0 - ring)
            ry0 = max(0, y0 - ring)
            rx1 = min(self.width, x1 + ring)
            ry1 = min(self.height, y1 + ring)
            region = occupancy[ry0:ry1, rx0:rx1]
            if np.any(region):
                return (ring - 1) / max(self.width, self.height)
        return max_ring / max(self.width, self.height)

    def _composite_alpha(self, canvas: np.ndarray, item: LayoutItem, alpha: np.ndarray) -> None:
        left = item.x - item.width / 2
        top = item.y - item.height / 2
        target_w = max(1, round(item.width * self.width))
        target_h = max(1, round(item.height * self.height))
        if target_w <= 0 or target_h <= 0:
            return

        source_h, source_w = alpha.shape
        scale = min(target_w / max(1, source_w), target_h / max(1, source_h))
        fit_w = max(1, min(target_w, round(source_w * scale)))
        fit_h = max(1, min(target_h, round(source_h * scale)))
        resized = Image.fromarray(alpha, mode="L").resize((fit_w, fit_h), Image.Resampling.BILINEAR)
        visible = np.asarray(resized, dtype=np.uint8) >= self._MIN_ALPHA

        base_x = round(left * self.width) + (target_w - fit_w) // 2
        base_y = round(top * self.height) + (target_h - fit_h) // 2
        dst_x0 = max(0, base_x)
        dst_y0 = max(0, base_y)
        dst_x1 = min(self.width, base_x + fit_w)
        dst_y1 = min(self.height, base_y + fit_h)
        if dst_x1 <= dst_x0 or dst_y1 <= dst_y0:
            return
        src_x0 = dst_x0 - base_x
        src_y0 = dst_y0 - base_y
        src_x1 = src_x0 + (dst_x1 - dst_x0)
        src_y1 = src_y0 + (dst_y1 - dst_y0)
        canvas[dst_y0:dst_y1, dst_x0:dst_x1] |= visible[src_y0:src_y1, src_x0:src_x1]

    def _alpha(self, path: Path) -> np.ndarray | None:
        if path in self._alpha_cache:
            return self._alpha_cache[path]
        try:
            with Image.open(path) as opened:
                alpha = np.asarray(opened.convert("RGBA").getchannel("A"), dtype=np.uint8).copy()
        except (OSError, ValueError):
            alpha = None
        self._alpha_cache[path] = alpha
        return alpha

    def _fill_box(self, canvas: np.ndarray, box: Box) -> None:
        x0, y0, x1, y1 = self._pixel_box(box)
        if x1 > x0 and y1 > y0:
            canvas[y0:y1, x0:x1] = True

    def _pixel_box(self, box: Box) -> tuple[int, int, int, int]:
        x0 = max(0, min(self.width, int(np.floor(box[0] * self.width))))
        y0 = max(0, min(self.height, int(np.floor(box[1] * self.height))))
        x1 = max(0, min(self.width, int(np.ceil(box[2] * self.width))))
        y1 = max(0, min(self.height, int(np.ceil(box[3] * self.height))))
        return x0, y0, x1, y1

    @staticmethod
    def _layout_box(item: LayoutItem) -> Box:
        return (
            item.x - item.width / 2,
            item.y - item.height / 2,
            item.x + item.width / 2,
            item.y + item.height / 2,
        )
