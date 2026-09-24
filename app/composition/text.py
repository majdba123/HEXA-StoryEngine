from __future__ import annotations

from collections import defaultdict

from app.composition.text_director import PlacedTextRegion, TextPlacementDirector
from app.models import CompositionBeat, MotionCue, StoryBeat, TextCompositionBeat, TextCue, VisualAsset
from app.text.timing.visibility import TextVisibilityPolicy


class TextCompositionPlanner:
    """Compose text independently while preserving authored Final Package visuals."""

    def __init__(self) -> None:
        self.director = TextPlacementDirector()
        self.visibility = TextVisibilityPolicy()

    def plan(
        self,
        beats: list[StoryBeat],
        visual_composition: list[CompositionBeat],
        text_cues: list[TextCue],
        assets: list[VisualAsset] | None = None,
        visual_motion: list[MotionCue] | None = None,
        repair_level: int = 0,
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
                    repair_level=repair_level,
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
                # placement is actually clean. Unsafe layouts must be free to move.
                if result.visual_overlap <= 0.015:
                    preferred_zone_by_scene[beat.scene_id] = self.director._zone_family(
                        result.zone
                    )

            output.append(TextCompositionBeat(beat_id=beat.id, items=items))

        return output

    @staticmethod
    def _visual_for_text_window(
        *,
        beat: StoryBeat,
        visual: CompositionBeat | None,
        visible_end: float,
        motion_by_key: dict[tuple[str, str], MotionCue],
    ) -> CompositionBeat | None:
        """Use final Motion timing when repairing text after Motion planning.

        Initial authoring has no Motion and therefore falls back to Story V2 timing in
        TextPlacementDirector. Recovery calls this planner again with Motion available,
        giving text placement the exact rendered reveal schedule.
        """
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
