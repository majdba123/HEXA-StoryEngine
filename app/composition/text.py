from __future__ import annotations

from collections import defaultdict

from app.composition.text_director import PlacedTextRegion, PlacementResult, TextPlacementDirector
from app.layout.connection_geometry import connector_endpoints
from app.models import CompositionBeat, MotionCue, StoryBeat, TextCompositionBeat, TextCue, VisualAsset
from app.targets import frame_size
from app.text.timing.visibility import TextVisibilityPolicy


class TextCompositionPlanner:
    """Compose text independently while preserving authored Final Package visuals."""

    def __init__(self) -> None:
        self.director = TextPlacementDirector()
        self.visibility = TextVisibilityPolicy()
        # One audit row per cue from the last plan() call (Sprint 4.5 owner coupling).
        self.owner_coupling: list[dict] = []

    def plan(
        self,
        beats: list[StoryBeat],
        visual_composition: list[CompositionBeat],
        text_cues: list[TextCue],
        assets: list[VisualAsset] | None = None,
        visual_motion: list[MotionCue] | None = None,
    ) -> list[TextCompositionBeat]:
        visual_by_beat = {beat.beat_id: beat for beat in visual_composition}
        assets_by_id = {asset.id: asset for asset in (assets or [])}
        motion_by_key = {
            (cue.beat_id, cue.asset_id): cue
            for cue in (visual_motion or [])
        }
        cues_by_beat: dict[str, list[TextCue]] = defaultdict(list)
        for cue in text_cues:
            cues_by_beat[cue.beat_id].append(cue)

        preferred_zone_by_scene: dict[str, str] = {}
        output: list[TextCompositionBeat] = []
        self.owner_coupling = []

        for beat in beats:
            cues = sorted(
                cues_by_beat.get(beat.id, []),
                key=lambda cue: (cue.spoken_start, -cue.priority, cue.id),
            )
            if not cues:
                continue

            visual = visual_by_beat.get(beat.id)
            placed: list[PlacedTextRegion] = []
            items = []

            for cue in cues:
                visible_end = self.visibility.visible_end(cue, beat, cues)
                concurrent = [
                    row
                    for row in placed
                    if self.visibility.overlaps(
                        cue.spoken_start,
                        visible_end,
                        row.start,
                        row.end,
                    )
                ]
                cue_visual = self._visual_for_text_window(
                    beat=beat,
                    visual=visual,
                    visible_end=visible_end,
                    motion_by_key=motion_by_key,
                )
                result = self.director.place(
                    beat=beat,
                    visual=cue_visual,
                    cue=cue,
                    concurrent_text=concurrent,
                    preferred_zone=preferred_zone_by_scene.get(beat.scene_id),
                    assets_by_id=assets_by_id,
                    visible_end=visible_end,
                    visual_visibility_resolved=bool(motion_by_key),
                )
                if result is None:
                    continue
                certified = result
                result = self._couple_to_authored_owner(
                    beat=beat,
                    visual=visual,
                    cue_visual=cue_visual,
                    cue=cue,
                    result=certified,
                    concurrent=concurrent,
                    visible_end=visible_end,
                    motion_by_key=motion_by_key,
                    assets_by_id=assets_by_id,
                )
                items.append(result.item)
                placed.append(
                    PlacedTextRegion(
                        cue_id=cue.id,
                        start=cue.spoken_start,
                        end=visible_end,
                        box=result.box,
                        zone=result.zone,
                    )
                )

                # Preserve a soft scene-level typography lane only when the selected
                # placement is actually clean. Unsafe layouts must be free to move. The
                # lane follows the certified placement: owner coupling is local to one
                # cue and never steers later cues.
                if certified.visual_overlap <= 0.015:
                    preferred_zone_by_scene[beat.scene_id] = self.director._zone_family(
                        certified.zone
                    )

            if items:
                output.append(TextCompositionBeat(beat_id=beat.id, items=items))

        return output

    def _couple_to_authored_owner(
        self,
        *,
        beat: StoryBeat,
        visual: CompositionBeat | None,
        cue_visual: CompositionBeat | None,
        cue: TextCue,
        result: PlacementResult,
        concurrent: list[PlacedTextRegion],
        visible_end: float,
        motion_by_key: dict[tuple[str, str], MotionCue],
        assets_by_id: dict[str, VisualAsset],
    ) -> PlacementResult:
        """Sprint 4.5: sit a label beside its owner only on explicit, on-screen ownership.

        Placement only: text timing is never touched, and every abstention keeps the
        certified placement. The owner must be authored, already on screen when the text
        appears and still on screen for the whole text interval.
        """
        row = {"beat_id": beat.id, "text_cue_id": cue.id, "anchor_asset_id": cue.anchor_asset_id}
        reason = self._owner_abstention(beat, visual, cue_visual, cue, visible_end, motion_by_key)
        if reason is not None:
            self.owner_coupling.append({**row, "decision": "abstained", "reason": reason})
            return result
        owner = next(item for item in cue_visual.items if item.asset_id == cue.anchor_asset_id)
        coupled, audit = self.director.couple_to_owner(
            beat=beat,
            visual=cue_visual,
            cue=cue,
            owner=owner,
            current=result,
            concurrent_text=concurrent,
            assets_by_id=assets_by_id,
            connectors=self._connectors(beat, cue_visual, motion_by_key),
        )
        self.owner_coupling.append({**row, **audit})
        return coupled or result

    @staticmethod
    def _owner_abstention(
        beat: StoryBeat,
        visual: CompositionBeat | None,
        cue_visual: CompositionBeat | None,
        cue: TextCue,
        visible_end: float,
        motion_by_key: dict[tuple[str, str], MotionCue],
    ) -> str | None:
        if not cue.anchor_asset_id or "final_package_text_anchor" not in cue.package_evidence:
            return "ownership_not_authored"
        if visual is None or cue_visual is None or not motion_by_key:
            return "final_visual_timing_unknown"
        if not any(item.asset_id == cue.anchor_asset_id for item in visual.items):
            return "owner_not_in_scene"
        if beat.active_visual_semantic_state is not None and (
            cue.anchor_asset_id not in beat.active_visual_semantic_state
        ):
            return "owner_not_in_scene"

        def visible_start(motion_cue: MotionCue) -> float:
            starts = [float(segment.start) for segment in motion_cue.segments if segment.phase != "EXIT"]
            return min([float(motion_cue.start), *starts])

        owner_cue = motion_by_key.get((beat.id, cue.anchor_asset_id))
        if owner_cue is None:
            return "final_visual_timing_unknown"
        owner_start = visible_start(owner_cue)
        scene_start = min(
            visible_start(row) for (beat_id, _), row in motion_by_key.items() if beat_id == beat.id
        )
        if owner_start >= visible_end:
            return "future_owner"  # the owner appears only after the text is gone
        if float(cue.spoken_start) < scene_start - 1e-6:
            return "held_previous_scene"  # the text shows before its own scene does
        if owner_start > float(cue.spoken_start) + 1e-6:
            return "owner_absent_when_text_appears"
        if visible_end > float(beat.end) + 1e-6:
            return "owner_not_present_through_text"
        return None

    @staticmethod
    def _connectors(
        beat: StoryBeat,
        visual: CompositionBeat,
        motion_by_key: dict[tuple[str, str], MotionCue],
        canvas: tuple[int, int] | None = None,
    ) -> list[tuple[tuple[float, float], tuple[float, float]]]:
        """Authored connector lines that can be drawn in this beat (Composition boxes)."""
        canvas = canvas or frame_size()
        rects = {
            item.asset_id: (
                (item.x - item.width / 2) * canvas[0], (item.y - item.height / 2) * canvas[1],
                (item.x + item.width / 2) * canvas[0], (item.y + item.height / 2) * canvas[1],
            )
            for item in visual.items
        }
        lines = []
        for (beat_id, _), motion_cue in motion_by_key.items():
            if beat_id != beat.id:
                continue
            for segment in motion_cue.segments:
                source, target = segment.source_asset_id, segment.target_asset_id
                if not segment.connection or source not in rects or target not in rects:
                    continue
                others = [rect for asset_id, rect in rects.items() if asset_id not in {source, target}]
                points = connector_endpoints(rects[source], rects[target], others)
                if points is not None:
                    lines.append(points)
        return lines

    @staticmethod
    def _visual_for_text_window(
        *,
        beat: StoryBeat,
        visual: CompositionBeat | None,
        visible_end: float,
        motion_by_key: dict[tuple[str, str], MotionCue],
    ) -> CompositionBeat | None:
        """Use final Motion timing during the single primary text-authoring pass."""
        if visual is None or not motion_by_key:
            return visual
        starts = [
            float(cue.start)
            for item in visual.items
            if (cue := motion_by_key.get((beat.id, item.asset_id))) is not None
        ]
        earliest = min(starts) if starts else None
        carrier_limit = earliest + 0.08 if earliest is not None else None
        visible_items = []
        for item in visual.items:
            cue = motion_by_key.get((beat.id, item.asset_id))
            if cue is None:
                visible_items.append(item)
                continue
            start = float(cue.start)
            if start < visible_end - 0.01:
                visible_items.append(item)
                continue
            if carrier_limit is not None and start <= carrier_limit + 1e-9:
                visible_items.append(item)
        return visual.model_copy(update={"items": visible_items})
