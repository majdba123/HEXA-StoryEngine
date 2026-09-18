from __future__ import annotations

from app.choreography import ChoreographyPlan
from app.director import SceneDirection
from app.layout import ConstraintLayoutSolver
from app.models import CompositionBeat, LayoutItem, StoryBeat, VisualAsset

from .states import CompositionStateDirector


class CompositionPlanner:
    """Preserve Final Package authored geometry and repair only unsafe layouts.

    Pass2 full-canvas alpha layers must share the same authored transform; treating each
    one as a new independent rectangle destroys registration and causes the exact
    overlap/misplacement failure this planner is designed to prevent.
    """

    def __init__(self, *, solver: ConstraintLayoutSolver | None = None) -> None:
        self.states = CompositionStateDirector()
        self.solver = solver or ConstraintLayoutSolver()

    def plan(
        self,
        beats: list[StoryBeat],
        assets: list[VisualAsset] | None = None,
        choreography: ChoreographyPlan | None = None,
        directions: list[SceneDirection] | None = None,
    ) -> list[CompositionBeat]:
        by_id = {asset.id: asset for asset in (assets or [])}
        direction_by_beat = {row.beat_id: row for row in (directions or [])}
        base_by_beat: dict[str, CompositionBeat] = {}
        output: list[CompositionBeat] = []

        for beat in beats:
            ids = list(dict.fromkeys([*beat.primary_asset_ids, *beat.support_asset_ids]))
            selected = [by_id[asset_id] for asset_id in ids if asset_id in by_id]
            if selected and all(self._has_source_geometry(asset) for asset in selected):
                items = self._source_relative_layout(selected)
            else:
                items = self._fallback_layout(ids)
            direction = direction_by_beat.get(beat.id)
            evidence = list(direction.evidence) if direction else []
            base = CompositionBeat(
                beat_id=beat.id,
                items=items,
                state_evidence=evidence,
                semantic_focus_asset_id=direction.primary_asset_id if direction else None,
            )
            base_by_beat[beat.id] = base
            output.append(base)

        directed = self.states.apply(beats, output, choreography)
        repaired: list[CompositionBeat] = []
        for layout in directed:
            base = base_by_beat[layout.beat_id]
            restored = self._restore_family_canvas_geometry(layout, base, by_id)
            repaired.append(self.solver.solve(restored, list(by_id.values())))
        return repaired

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

        target_w = 0.88
        target_h = 0.82
        source_aspect = source_width / max(1, source_height)
        output_aspect = 16 / 9
        union_norm_w = union_w / source_width
        union_norm_h = union_h / source_height
        x_metric = union_norm_w * source_aspect / output_aspect
        y_metric = union_norm_h
        scale = min(target_w / max(0.01, x_metric), target_h / max(0.01, y_metric))

        center_x = 0.50
        center_y = 0.51
        union_center_x = (x0 + x1) / 2 / source_width
        union_center_y = (y0 + y1) / 2 / source_height

        items: list[LayoutItem] = []
        for index, asset in enumerate(assets):
            if asset.render_as_family_canvas:
                bx, by, bw, bh = (0, 0, source_width, source_height)
            else:
                bx, by, bw, bh = asset.source_bbox or (0, 0, source_width, source_height)
            source_center_x = (bx + bw / 2) / source_width
            source_center_y = (by + bh / 2) / source_height
            rel_x = (source_center_x - union_center_x) * source_aspect / output_aspect
            rel_y = source_center_y - union_center_y
            width = (bw / source_width) * source_aspect / output_aspect * scale
            height = (bh / source_height) * scale
            items.append(LayoutItem(
                asset_id=asset.id,
                x=center_x + rel_x * scale,
                y=center_y + rel_y * scale,
                width=max(0.05, width),
                height=max(0.07, height),
                z=20 if index == 0 else 10 + max(0, len(assets) - index),
                placement_source="authored",
            ))
        return items

    @staticmethod
    def _restore_family_canvas_geometry(
        directed: CompositionBeat,
        base: CompositionBeat,
        by_id: dict[str, VisualAsset],
    ) -> CompositionBeat:
        authored = {item.asset_id: item for item in base.items}
        items: list[LayoutItem] = []
        for item in directed.items:
            asset = by_id.get(item.asset_id)
            original = authored.get(item.asset_id)
            if asset and asset.render_as_family_canvas and original:
                items.append(item.model_copy(update={
                    "x": original.x,
                    "y": original.y,
                    "width": original.width,
                    "height": original.height,
                    "placement_source": "authored_family_canvas",
                }))
            else:
                items.append(item)
        return directed.model_copy(update={"items": items})

    @staticmethod
    def _fallback_layout(ids: list[str]) -> list[LayoutItem]:
        items: list[LayoutItem] = []
        if len(ids) == 1:
            items.append(LayoutItem(asset_id=ids[0], x=0.5, y=0.52, width=0.64, height=0.76, z=20, placement_source="fallback"))
        elif len(ids) == 2:
            items.extend([
                LayoutItem(asset_id=ids[0], x=0.32, y=0.52, width=0.46, height=0.68, z=20, placement_source="fallback"),
                LayoutItem(asset_id=ids[1], x=0.72, y=0.52, width=0.38, height=0.56, z=15, placement_source="fallback"),
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
                    placement_source="fallback",
                ))
        return items
