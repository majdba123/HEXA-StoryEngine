from __future__ import annotations

from app.models import CompositionBeat, LayoutItem, StoryBeat


class CompositionPlanner:
    """Simple deterministic baseline with deliberate screen occupancy."""

    def plan(self, beats: list[StoryBeat]) -> list[CompositionBeat]:
        output: list[CompositionBeat] = []
        for beat in beats:
            ids = beat.primary_asset_ids + beat.support_asset_ids
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
                support = ids[1:3]
                for idx, asset_id in enumerate(support):
                    items.append(LayoutItem(
                        asset_id=asset_id,
                        x=0.70,
                        y=0.36 + idx * 0.32,
                        width=0.27,
                        height=0.32,
                        z=5,
                    ))
            output.append(CompositionBeat(beat_id=beat.id, items=items))
        return output
