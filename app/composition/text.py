from __future__ import annotations

from collections import defaultdict

from app.composition.text_director import PlacedTextRegion, TextPlacementDirector
from app.models import CompositionBeat, StoryBeat, TextCompositionBeat, TextCue, VisualAsset
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
    ) -> list[TextCompositionBeat]:
        visual_by_beat = {beat.beat_id: beat for beat in visual_composition}
        assets_by_id = {asset.id: asset for asset in (assets or [])}
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
                result = self.director.place(
                    beat=beat,
                    visual=visual,
                    cue=cue,
                    concurrent_text=concurrent,
                    preferred_zone=preferred_zone_by_scene.get(beat.scene_id),
                    assets_by_id=assets_by_id,
                    visible_end=visible_end,
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
