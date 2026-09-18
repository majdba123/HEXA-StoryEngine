from __future__ import annotations

from pathlib import Path

from PIL import Image

from app.models import VisualAsset


class AssetManager:
    """Normalize cutout lineage without discarding independently animatable layers.

    Pass2 emits a main layer plus one or more secondary alpha layers using the same
    source canvas. They are a family, not unrelated objects. The family metadata lets
    Composition keep their authored registration while Motion can still animate them.
    """

    @staticmethod
    def normalize(assets: list[VisualAsset]) -> list[VisualAsset]:
        output: list[VisualAsset] = []
        for asset in assets:
            family = AssetManager.family_id(asset)
            parent = family if family != asset.id else None
            full_canvas = AssetManager._is_full_canvas_layer(asset)
            output.append(asset.model_copy(update={
                "parent_asset_id": asset.parent_asset_id or parent,
                "asset_family_id": asset.asset_family_id or family,
                "render_as_family_canvas": asset.render_as_family_canvas or full_canvas,
            }))
        return output

    @staticmethod
    def family_id(asset: VisualAsset) -> str:
        if asset.asset_family_id:
            return asset.asset_family_id
        marker = ":secondary-"
        if marker in asset.id:
            return asset.id.split(marker, 1)[0]
        return asset.id

    @staticmethod
    def _is_full_canvas_layer(asset: VisualAsset) -> bool:
        method = asset.extraction_method.lower()
        if "pass2_" not in method and "refined_" not in method:
            return False
        if not asset.source_canvas_width or not asset.source_canvas_height:
            return False
        path = Path(asset.image_path)
        try:
            with Image.open(path) as image:
                return image.size == (asset.source_canvas_width, asset.source_canvas_height)
        except (OSError, ValueError):
            return False
