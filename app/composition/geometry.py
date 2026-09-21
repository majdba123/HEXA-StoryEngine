from __future__ import annotations

from dataclasses import dataclass

from app.models import LayoutItem, VisualAsset


@dataclass(frozen=True, slots=True)
class SceneFit:
    """Map Final Package source-canvas pixels into the render canvas without re-layout."""

    x: float
    y: float
    width: float
    height: float


class AuthoredGeometryMapper:
    """Treat Final Package geometry as the authoritative visual destination.

    ``source_bbox`` is measured in the original scene image. The mapper performs only
    the single contain-fit needed to place that complete source scene inside the render
    aspect ratio. It never recenters a subset of assets and never spreads items based on
    count. Therefore adding a new cutout cannot move any existing cutout.
    """

    def __init__(self, *, output_aspect: float = 16 / 9) -> None:
        self.output_aspect = output_aspect

    def item(self, asset: VisualAsset, *, z: int = 10) -> LayoutItem | None:
        if not self.has_geometry(asset):
            return None
        assert asset.source_bbox is not None
        assert asset.source_canvas_width is not None
        assert asset.source_canvas_height is not None
        fit = self.scene_fit(asset.source_canvas_width, asset.source_canvas_height)
        bx, by, bw, bh = asset.source_bbox
        sw = float(asset.source_canvas_width)
        sh = float(asset.source_canvas_height)
        return LayoutItem(
            asset_id=asset.id,
            x=fit.x + ((bx + bw / 2.0) / sw) * fit.width,
            y=fit.y + ((by + bh / 2.0) / sh) * fit.height,
            width=max(1e-6, (bw / sw) * fit.width),
            height=max(1e-6, (bh / sh) * fit.height),
            z=z,
            placement_source="authored_scene_geometry",
        )

    def scene_fit(self, source_width: int, source_height: int) -> SceneFit:
        source_aspect = source_width / max(1.0, float(source_height))
        if source_aspect >= self.output_aspect:
            width = 1.0
            height = self.output_aspect / source_aspect
            return SceneFit(x=0.0, y=(1.0 - height) / 2.0, width=width, height=height)
        height = 1.0
        width = source_aspect / self.output_aspect
        return SceneFit(x=(1.0 - width) / 2.0, y=0.0, width=width, height=height)

    @staticmethod
    def has_geometry(asset: VisualAsset) -> bool:
        if not (
            asset.source_bbox
            and asset.source_canvas_width
            and asset.source_canvas_height
            and asset.source_canvas_width > 0
            and asset.source_canvas_height > 0
        ):
            return False
        x, y, width, height = asset.source_bbox
        return bool(
            width > 0
            and height > 0
            and x >= 0
            and y >= 0
            and x + width <= asset.source_canvas_width + 1
            and y + height <= asset.source_canvas_height + 1
        )
