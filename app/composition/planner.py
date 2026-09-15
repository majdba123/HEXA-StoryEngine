from __future__ import annotations

from app.models import CompositionBeat, LayoutItem, StoryBeat, VisualAsset


class CompositionPlanner:
    """Preserve the authored Final Package composition exactly at rest."""

    OUTPUT_ASPECT = 16 / 9

    def plan(
        self,
        beats: list[StoryBeat],
        assets: list[VisualAsset] | None = None,
    ) -> list[CompositionBeat]:
        by_id = {asset.id: asset for asset in (assets or [])}
        output: list[CompositionBeat] = []
        for beat in beats:
            ids = beat.primary_asset_ids + beat.support_asset_ids
            selected = [by_id[asset_id] for asset_id in ids if asset_id in by_id]
            if selected and all(self._has_source_geometry(asset) for asset in selected):
                items = self._source_exact_layout(selected)
            else:
                items = self._fallback_layout(ids)
            output.append(CompositionBeat(beat_id=beat.id, items=items))
        return output

    @staticmethod
    def _has_source_geometry(asset: VisualAsset) -> bool:
        return bool(
            asset.source_bbox
            and asset.source_canvas_width
            and asset.source_canvas_height
            and asset.source_canvas_width > 0
            and asset.source_canvas_height > 0
        )

    def _source_exact_layout(self, assets: list[VisualAsset]) -> list[LayoutItem]:
        source_width = int(assets[0].source_canvas_width or 1)
        source_height = int(assets[0].source_canvas_height or 1)
        source_aspect = source_width / max(1, source_height)

        if source_aspect >= self.OUTPUT_ASPECT:
            content_w = 1.0
            content_h = self.OUTPUT_ASPECT / source_aspect
            offset_x = 0.0
            offset_y = (1.0 - content_h) / 2.0
        else:
            content_h = 1.0
            content_w = source_aspect / self.OUTPUT_ASPECT
            offset_x = (1.0 - content_w) / 2.0
            offset_y = 0.0

        items: list[LayoutItem] = []
        for index, asset in enumerate(assets):
            bx, by, bw, bh = asset.source_bbox or (0, 0, source_width, source_height)
            x = offset_x + ((bx + bw / 2) / source_width) * content_w
            y = offset_y + ((by + bh / 2) / source_height) * content_h
            width = (bw / source_width) * content_w
            height = (bh / source_height) * content_h
            items.append(LayoutItem(
                asset_id=asset.id,
                x=x,
                y=y,
                width=width,
                height=height,
                z=20 - index,
            ))
        return items

    @staticmethod
    def _fallback_layout(ids: list[str]) -> list[LayoutItem]:
        items: list[LayoutItem] = []
        if len(ids) == 1:
            items.append(LayoutItem(asset_id=ids[0], x=0.5, y=0.52, width=0.58, height=0.72, z=10))
        elif len(ids) == 2:
            items.extend([
                LayoutItem(asset_id=ids[0], x=0.34, y=0.52, width=0.45, height=0.66, z=10),
                LayoutItem(asset_id=ids[1], x=0.72, y=0.52, width=0.30, height=0.48, z=5),
            ])
        elif ids:
            items.append(LayoutItem(asset_id=ids[0], x=0.34, y=0.52, width=0.42, height=0.64, z=10))
            for idx, asset_id in enumerate(ids[1:3]):
                items.append(LayoutItem(
                    asset_id=asset_id,
                    x=0.70,
                    y=0.36 + idx * 0.32,
                    width=0.27,
                    height=0.32,
                    z=5,
                ))
        return items
