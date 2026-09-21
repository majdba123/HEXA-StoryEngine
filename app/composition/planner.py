from __future__ import annotations

from collections import defaultdict

from app.choreography import ChoreographyPlan
from app.director import SceneDirection
from app.layout import ConstraintLayoutSolver
from app.models import CompositionBeat, LayoutItem, StoryBeat, VisualAsset

from .geometry import AuthoredGeometryMapper
from .states import CompositionStateDirector


class CompositionPlanner:
    """Reconstruct the authored Final Package scene; never redesign it.

    Cutout stages answer *what can move*. Story/Choreography answer *when/why it moves*.
    Composition has one spatial responsibility: map every extracted scene asset back to
    its authoritative source location. Asset count is therefore irrelevant to layout.
    """

    def __init__(self, *, solver: ConstraintLayoutSolver | None = None) -> None:
        self.states = CompositionStateDirector()
        self.solver = solver or ConstraintLayoutSolver()
        self.geometry = AuthoredGeometryMapper()

    def plan(
        self,
        beats: list[StoryBeat],
        assets: list[VisualAsset] | None = None,
        choreography: ChoreographyPlan | None = None,
        directions: list[SceneDirection] | None = None,
    ) -> list[CompositionBeat]:
        all_assets = list(assets or [])
        by_scene: dict[str, list[VisualAsset]] = defaultdict(list)
        for asset in all_assets:
            by_scene[asset.scene_id].append(asset)
        direction_by_beat = {row.beat_id: row for row in (directions or [])}

        output: list[CompositionBeat] = []
        for beat in beats:
            scene_assets = by_scene.get(beat.scene_id, [])
            items = self._scene_layout(scene_assets)
            direction = direction_by_beat.get(beat.id)
            evidence = list(direction.evidence) if direction else []
            evidence.append("layout:final_package_geometry")
            output.append(CompositionBeat(
                beat_id=beat.id,
                items=items,
                state_evidence=list(dict.fromkeys(evidence)),
                semantic_focus_asset_id=direction.primary_asset_id if direction else None,
            ))

        # State direction may annotate semantic state/focus, but it is forbidden from
        # changing x/y/width/height. The solver likewise treats authored geometry as a
        # lock and only repairs legacy/fallback items lacking source geometry.
        directed = self.states.apply(beats, output, choreography)
        return [self.solver.solve(layout, all_assets) for layout in directed]

    def _scene_layout(self, assets: list[VisualAsset]) -> list[LayoutItem]:
        if not assets:
            return []

        authored: list[LayoutItem] = []
        missing: list[VisualAsset] = []
        for index, asset in enumerate(assets):
            item = self.geometry.item(asset, z=10 + index)
            if item is None:
                missing.append(asset)
            else:
                authored.append(item)

        if not missing:
            return authored

        # Legacy/externally supplied assets without source geometry get deterministic
        # fallback slots. Crucially, these slots never move authored items.
        fallback = self._fallback_layout([asset.id for asset in missing], z_base=10 + len(authored))
        return [*authored, *fallback]

    @staticmethod
    def _fallback_layout(ids: list[str], *, z_base: int = 10) -> list[LayoutItem]:
        if not ids:
            return []
        columns = min(4, max(1, len(ids)))
        rows = (len(ids) + columns - 1) // columns
        width = min(0.30, 0.78 / columns)
        height = min(0.34, 0.72 / max(1, rows))
        items: list[LayoutItem] = []
        for index, asset_id in enumerate(ids):
            col = index % columns
            row = index // columns
            x = 0.11 + (col + 0.5) * (0.78 / columns)
            y = 0.14 + (row + 0.5) * (0.72 / max(1, rows))
            items.append(LayoutItem(
                asset_id=asset_id,
                x=x,
                y=y,
                width=width,
                height=height,
                z=z_base + index,
                placement_source="fallback_missing_source_geometry",
            ))
        return items
