from __future__ import annotations

from collections import defaultdict

from app.choreography import ChoreographyPlan
from app.director import SceneDirection
from app.layout import ConstraintLayoutSolver
from app.models import CompositionBeat, LayoutItem, StoryBeat, VisualAsset
from app.shared.errors import StageFailedError
from app.targets import VisualTargetProfile, active_target, composition_policy

from .geometry import AuthoredGeometryMapper
from .semantic_staging import SemanticStagingPlanner
from .states import CompositionStateDirector


class CompositionPlanner:
    """Reconstruct the authored Final Package scene; never redesign it.

    Cutout stages answer *what can move*. Story/Choreography answer *when/why it moves*.
    Composition has one spatial responsibility: map every extracted scene asset back to
    its authoritative source location. Asset count is therefore irrelevant to layout.
    The single exception is Sprint 4.3 semantic staging: a bounded, rigid, audited nudge
    of one asset family, only when it makes an authored relation clearly readable.

    Output format: the authored scene is first mapped to the 16:9 reference geometry,
    then the target's composition policy projects it onto the target frame (identity
    for the reference target, responsive reflow otherwise) before the shared staging/state/solver
    contracts run on the target geometry. ``target`` defaults to the active target.
    """

    def __init__(
        self,
        *,
        solver: ConstraintLayoutSolver | None = None,
        target: VisualTargetProfile | None = None,
    ) -> None:
        self.target = target
        self.states = CompositionStateDirector()
        self.solver = solver or ConstraintLayoutSolver()
        self.geometry = AuthoredGeometryMapper()
        self.staging = SemanticStagingPlanner(footprints=self.solver.footprints)

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
        self.target_evidence: dict[str, str] = {}
        staged = self._stage_scenes(beats, by_scene, choreography)

        output: list[CompositionBeat] = []
        for beat in beats:
            items, staging_evidence = staged[beat.scene_id]
            direction = direction_by_beat.get(beat.id)
            evidence = list(direction.evidence) if direction else []
            evidence.append("layout:final_package_geometry")
            evidence.append(staging_evidence)
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
        solved = [self.solver.solve(layout, all_assets) for layout in directed]
        self._require_owned_contracts(beats=beats, layouts=solved, assets=all_assets)
        return solved

    def _stage_scenes(
        self,
        beats: list[StoryBeat],
        by_scene: dict[str, list[VisualAsset]],
        choreography: ChoreographyPlan | None,
    ) -> dict[str, tuple[list[LayoutItem], str]]:
        """Resolve target projection and Sprint 4.3 staging once per scene (all its beats)."""
        policy = composition_policy(self.target or active_target())
        directives: dict[str, list] = defaultdict(list)
        for beat in beats:
            directive = choreography.for_beat(beat.id) if choreography else None
            if directive is not None:
                directives[beat.scene_id].append(directive)
        staged: dict[str, tuple[list[LayoutItem], str]] = {}
        for scene_id in dict.fromkeys(beat.scene_id for beat in beats):
            scene_assets = by_scene.get(scene_id, [])
            projection = policy.project(
                self._scene_layout(scene_assets), scene_assets, directives[scene_id],
            )
            result = self.staging.stage(projection.items, scene_assets, directives[scene_id])
            staged[scene_id] = (result.items, result.evidence)
            self.target_evidence[scene_id] = projection.evidence
        return staged

    def _require_owned_contracts(
        self,
        *,
        beats: list[StoryBeat],
        layouts: list[CompositionBeat],
        assets: list[VisualAsset],
    ) -> None:
        """Refuse a Composition result that loses assets or violates source geometry."""
        assets_by_scene: dict[str, set[str]] = defaultdict(set)
        by_id = {asset.id: asset for asset in assets}
        for asset in assets:
            if asset.can_animate_independently:
                assets_by_scene[asset.scene_id].add(asset.id)

        layout_by_beat = {layout.beat_id: layout for layout in layouts}
        for beat in beats:
            layout = layout_by_beat.get(beat.id)
            actual = {item.asset_id for item in layout.items} if layout else set()
            missing = sorted(assets_by_scene.get(beat.scene_id, set()) - actual)
            if missing:
                raise StageFailedError(
                    "Composition dropped independently animatable assets",
                    details={
                        "code": "ASSET_REACHES_COMPOSITION",
                        "beat_id": beat.id,
                        "asset_ids": missing,
                    },
                )
            violations = self.solver.inspect(layout.items if layout else [], by_id)
            if violations:
                raise StageFailedError(
                    "Composition produced geometry outside the authored layout contract",
                    details={
                        "code": "LAYOUT_REFERENCE_VIOLATION",
                        "beat_id": beat.id,
                        "violations": violations[:20],
                    },
                )

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
