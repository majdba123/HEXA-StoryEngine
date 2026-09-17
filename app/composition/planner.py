from __future__ import annotations

from app.choreography import ChoreographyPlan
from app.models import CompositionBeat, LayoutItem, StoryBeat, VisualAsset

from .states import CompositionStateDirector


class CompositionPlanner:
    """Recompose separated objects while preserving the source scene's visual grammar.

    The Final Package image remains a layout reference, not a poster to animate. We
    normalize extracted object positions from the source scene, then fit their union
    into a deliberate safe area so the screen is occupied similarly to the authored
    scene while every object remains independently animatable.
    """

    def __init__(self) -> None:
        self.states = CompositionStateDirector()

    def plan(
        self,
        beats: list[StoryBeat],
        assets: list[VisualAsset] | None = None,
        choreography: ChoreographyPlan | None = None,
    ) -> list[CompositionBeat]:
        by_id = {asset.id: asset for asset in (assets or [])}
        output: list[CompositionBeat] = []
        for beat in beats:
            ids = beat.primary_asset_ids + beat.support_asset_ids
            selected = [by_id[asset_id] for asset_id in ids if asset_id in by_id]
            if selected and all(self._has_source_geometry(asset) for asset in selected):
                items = self._source_relative_layout(selected)
            else:
                items = self._fallback_layout(ids)
            output.append(CompositionBeat(beat_id=beat.id, items=items))
        return self.states.apply(beats, output, choreography)

    @staticmethod
    def _has_source_geometry(asset: VisualAsset) -> bool:
        return bool(
            asset.source_bbox
            and asset.source_canvas_width
            and asset.source_canvas_height
            and asset.source_canvas_width > 0
            and asset.source_canvas_height > 0
        )

    def _source_relative_layout(self, assets: list[VisualAsset]) -> list[LayoutItem]:
        source_width = max(int(asset.source_canvas_width or 1) for asset in assets)
        source_height = max(int(asset.source_canvas_height or 1) for asset in assets)
        boxes = [asset.source_bbox for asset in assets if asset.source_bbox]
        x0 = min(box[0] for box in boxes)
        y0 = min(box[1] for box in boxes)
        x1 = max(box[0] + box[2] for box in boxes)
        y1 = max(box[1] + box[3] for box in boxes)
        union_w = max(1, x1 - x0)
        union_h = max(1, y1 - y0)

        # Fit the authored object cluster into a large but safe canvas region. The
        # scale is based on the union, not per-object heuristics, so relative spacing
        # and hierarchy survive extraction.
        target_w = 0.88
        target_h = 0.82
        source_aspect = source_width / max(1, source_height)
        union_norm_w = union_w / source_width
        union_norm_h = union_h / source_height
        # Account for 16:9 output while preserving source-scene proportions.
        output_aspect = 16 / 9
        x_metric = union_norm_w * source_aspect / output_aspect
        y_metric = union_norm_h
        scale = min(target_w / max(0.01, x_metric), target_h / max(0.01, y_metric))

        center_x = 0.50
        center_y = 0.51
        union_center_x = (x0 + x1) / 2 / source_width
        union_center_y = (y0 + y1) / 2 / source_height

        items: list[LayoutItem] = []
        for index, asset in enumerate(assets):
            bx, by, bw, bh = asset.source_bbox or (0, 0, source_width, source_height)
            source_center_x = (bx + bw / 2) / source_width
            source_center_y = (by + bh / 2) / source_height
            rel_x = (source_center_x - union_center_x) * source_aspect / output_aspect
            rel_y = source_center_y - union_center_y
            width = (bw / source_width) * source_aspect / output_aspect * scale
            height = (bh / source_height) * scale
            items.append(LayoutItem(
                asset_id=asset.id,
                x=self._clamp(center_x + rel_x * scale, 0.04, 0.96),
                y=self._clamp(center_y + rel_y * scale, 0.05, 0.95),
                width=self._clamp(width, 0.05, 0.72),
                height=self._clamp(height, 0.07, 0.82),
                z=20 if index == 0 else 10 + max(0, len(assets) - index),
            ))
        return items

    @staticmethod
    def _fallback_layout(ids: list[str]) -> list[LayoutItem]:
        items: list[LayoutItem] = []
        if len(ids) == 1:
            items.append(LayoutItem(asset_id=ids[0], x=0.5, y=0.52, width=0.64, height=0.76, z=20))
        elif len(ids) == 2:
            items.extend([
                LayoutItem(asset_id=ids[0], x=0.32, y=0.52, width=0.46, height=0.68, z=20),
                LayoutItem(asset_id=ids[1], x=0.72, y=0.52, width=0.38, height=0.56, z=15),
            ])
        elif ids:
            columns = min(3, len(ids))
            for index, asset_id in enumerate(ids[:6]):
                col = index % columns
                row = index // columns
                items.append(LayoutItem(
                    asset_id=asset_id,
                    x=0.20 + col * (0.60 / max(1, columns - 1)),
                    y=0.38 + row * 0.34,
                    width=0.32 if index else 0.40,
                    height=0.42 if index else 0.54,
                    z=20 - index,
                ))
        return items

    @staticmethod
    def _clamp(value: float, low: float, high: float) -> float:
        return max(low, min(high, value))
