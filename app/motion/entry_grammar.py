from __future__ import annotations

from app.assets import AssetManager
from app.choreography import ChoreographyDirective, ChoreographyPlan
from app.models import CompositionBeat, LayoutItem, MotionCue, VisualAsset

from .timing import encoded_motion_renderability_floor_px, motion_comfort, projected_motion_activity_px

# Sprint 4.4: reference-derived entry motion. Measured reference entries ramp opacity over
# 3-13 frames (median 6) and half of them also scale in from ~0.94; none pop in one frame.
# The reveal frame itself must already be visible, so the ramp starts at a small opacity.
ENTRY_OPACITY_INITIAL = 0.14
ENTRY_OPACITY_MIN_SECONDS = 3 / 30
ENTRY_SCALE_IN = 0.94
_EPS = 1e-6
_FRAME = 1 / 30


class EntryMotionGrammar:
    """Give every newly entering asset an opacity entry inside its own Story window.

    Runs after the Reference contract, so it never competes with it: the opacity clock is
    a separate cue parameter, and the only transform it adds is a restrained scale-in for
    the Choreography leader when nothing else moves that asset. Story timing is input
    only: the clock is exactly ``[cue.start, cue.end]`` (reveal -> settle). Existing
    programs, segments and Sprint 4.1/4.2 motion are never rewritten.
    """

    def apply(
        self,
        cues: list[MotionCue],
        *,
        composition: list[CompositionBeat],
        choreography: ChoreographyPlan | None,
        assets: list[VisualAsset] | None,
    ) -> list[MotionCue]:
        assets_by_id = {asset.id: asset for asset in assets or []}
        layouts = {layout.beat_id: {item.asset_id: item for item in layout.items}
                   for layout in composition}
        by_beat: dict[str, list[int]] = {}
        for index, cue in enumerate(cues):
            by_beat.setdefault(cue.beat_id, []).append(index)
        output = list(cues)
        for beat_id, indices in by_beat.items():
            directive = choreography.for_beat(beat_id) if choreography is not None else None
            leader = directive.primary_asset_id if directive is not None else None
            beat_cues = [cues[i] for i in indices]
            families = self._family_sizes(beat_cues, assets_by_id)
            mismatched = self._mismatched_families(beat_cues, assets_by_id)
            openers = self._scene_opening_families(beat_cues, directive, assets_by_id)
            for i in indices:
                output[i] = self._apply_one(
                    cues[i],
                    item=layouts.get(beat_id, {}).get(cues[i].asset_id),
                    asset=assets_by_id.get(cues[i].asset_id),
                    is_leader=cues[i].asset_id == leader,
                    family_size=families.get(self._family(cues[i], assets_by_id), 1),
                    family_mismatch=self._family(cues[i], assets_by_id) in mismatched,
                    opens_scene=self._family(cues[i], assets_by_id) in openers
                    and self._in_opening_frame(cues[i], beat_cues),
                )
        return output

    def _apply_one(
        self,
        cue: MotionCue,
        *,
        item: LayoutItem | None,
        asset: VisualAsset | None,
        is_leader: bool,
        family_size: int,
        family_mismatch: bool,
        opens_scene: bool,
    ) -> MotionCue:
        params = dict(cue.params) if isinstance(cue.params, dict) else {}
        reason = self._opacity_blocker(cue, params, family_mismatch, opens_scene)
        if reason is not None:
            params["entry_grammar"] = {"opacity": False, "reason": reason}
            return cue.model_copy(update={"params": params})
        # One clock per cue; every layer of a Pass2 family shares identical start/settle,
        # so the family fades as one synchronized unit.
        params["entry_opacity"] = {
            "initial": ENTRY_OPACITY_INITIAL,
            "start": float(cue.start),
            "settle": float(cue.end),
        }
        scale_in = (
            is_leader and family_size == 1 and item is not None and asset is not None
            and self._scale_in_allowed(cue, params, item, asset)
        )
        if scale_in:
            program = dict(params["program"])
            program["name"] = "reference_entry_scale_in"
            program["settle_progress"] = 1.0
            program["keyframes"] = [
                {"progress": 0.0, "dx": 0.0, "dy": 0.0, "scale": ENTRY_SCALE_IN,
                 "easing": "ease_out_cubic"},
                {"progress": 1.0, "dx": 0.0, "dy": 0.0, "scale": 1.0, "easing": "ease_out_cubic"},
            ]
            params["program"] = program
        params["entry_grammar"] = {"opacity": True, "scale_in": scale_in}
        return cue.model_copy(update={"params": params})

    @staticmethod
    def _opacity_blocker(
        cue: MotionCue, params: dict, family_mismatch: bool, opens_scene: bool,
    ) -> str | None:
        continuity = params.get("semantic_continuity") or {}
        if continuity.get("mode", "ENTER") != "ENTER":
            return "not_entering"  # already on screen (or not visible): nothing to fade in
        if opens_scene:
            # The scene's authored opener carries the scene change at full opacity: a
            # faint first frame over an empty canvas is a near-white flash.
            return "opens_scene"
        if float(cue.end) - float(cue.start) + _EPS < ENTRY_OPACITY_MIN_SECONDS:
            return "short_window"
        if any(float(segment.start) < float(cue.start) - _EPS for segment in cue.segments):
            return "visible_before_reveal"  # a proxy segment shows it earlier: never hide it
        if family_mismatch:
            return "family_clock_mismatch"  # fail closed: a family fades together or not at all
        return None

    @staticmethod
    def _scale_in_allowed(cue: MotionCue, params: dict, item: LayoutItem, asset: VisualAsset) -> bool:
        """Leader scale-in only when no existing motion owns this asset's entry."""
        if cue.segments or asset.parent_asset_id:
            return False
        if (params.get("render_constraints") or {}).get("geometry_lock"):
            return False
        program = params.get("program") or {}
        frames = program.get("keyframes") or []
        if not frames or "compound_unit" in str(program.get("name") or ""):
            return False
        if any(
            abs(float(f.get("dx", 0.0))) > 1e-9 or abs(float(f.get("dy", 0.0))) > 1e-9
            or abs(float(f.get("scale", 1.0)) - 1.0) > 1e-9
            for f in frames
        ):
            return False  # a certified entry gesture already moves it: keep that, add opacity only
        delta = 1.0 - ENTRY_SCALE_IN
        activity = projected_motion_activity_px(
            dx=0.0, dy=0.0, scale=ENTRY_SCALE_IN, item_width=item.width, item_height=item.height,
        )
        if activity + _EPS < encoded_motion_renderability_floor_px():
            return False
        # ease_out_cubic peaks at 3x the mean speed at t=0; stay inside the ENTRY comfort speed.
        mean_speed = delta * min(item.width, item.height) / (float(cue.end) - float(cue.start))
        return mean_speed <= motion_comfort("ENTRY").max_normalized_speed

    @staticmethod
    def _in_opening_frame(cue: MotionCue, beat_cues: list[MotionCue]) -> bool:
        first = min(float(row.start) for row in beat_cues)
        return float(cue.start) < first + _FRAME + _EPS

    @classmethod
    def _scene_opening_families(
        cls,
        beat_cues: list[MotionCue],
        directive: ChoreographyDirective | None,
        assets_by_id: dict[str, VisualAsset],
    ) -> set[str]:
        """Families that keep the certified hard reveal in the beat's opening frame.

        Motion never ranks importance itself. One family opening alone is the opener by
        construction. Among several, existing authority decides: the single authored
        event leader, else Choreography's primary asset. Without such evidence every
        opening family keeps its hard reveal (fail closed).
        """
        opening = [cue for cue in beat_cues if cls._in_opening_frame(cue, beat_cues)]
        families = {cls._family(cue, assets_by_id) for cue in opening}
        if len(families) <= 1 or directive is None:
            return families
        leaders = {asset_id for flow in directive.event_flows for asset_id in flow.leader_asset_ids}
        led = {cls._family(cue, assets_by_id) for cue in opening if cue.asset_id in leaders}
        if len(led) == 1:
            return led
        primary = {cls._family(cue, assets_by_id) for cue in opening
                   if cue.asset_id == directive.primary_asset_id}
        return primary or families

    @staticmethod
    def _family(cue: MotionCue, assets_by_id: dict[str, VisualAsset]) -> str:
        asset = assets_by_id.get(cue.asset_id)
        return AssetManager.family_id(asset) if asset is not None else cue.asset_id

    @classmethod
    def _family_sizes(cls, cues: list[MotionCue], assets_by_id: dict[str, VisualAsset]) -> dict[str, int]:
        sizes: dict[str, int] = {}
        for cue in cues:
            family = cls._family(cue, assets_by_id)
            sizes[family] = sizes.get(family, 0) + 1
        return sizes

    @classmethod
    def _mismatched_families(cls, cues: list[MotionCue], assets_by_id: dict[str, VisualAsset]) -> set[str]:
        clocks: dict[str, set[tuple[float, float]]] = {}
        for cue in cues:
            clocks.setdefault(cls._family(cue, assets_by_id), set()).add(
                (round(float(cue.start), 6), round(float(cue.end), 6)))
        return {family for family, rows in clocks.items() if len(rows) > 1}
