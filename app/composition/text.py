from __future__ import annotations

from collections import defaultdict

from app.models import (
    CompositionBeat,
    StoryBeat,
    TextCompositionBeat,
    TextCue,
    TextLayoutItem,
)


class TextCompositionPlanner:
    """Place text independently from visual assets while respecting visual anchors."""

    def plan(
        self,
        beats: list[StoryBeat],
        visual_composition: list[CompositionBeat],
        text_cues: list[TextCue],
    ) -> list[TextCompositionBeat]:
        visual_by_beat = {beat.beat_id: beat for beat in visual_composition}
        cues_by_beat: dict[str, list[TextCue]] = defaultdict(list)
        for cue in text_cues:
            cues_by_beat[cue.beat_id].append(cue)

        output: list[TextCompositionBeat] = []
        for beat in beats:
            cues = sorted(
                cues_by_beat.get(beat.id, []),
                key=lambda cue: (cue.spoken_start, -cue.priority, cue.id),
            )
            if not cues:
                continue
            visual = visual_by_beat.get(beat.id)
            items = [
                self._layout_item(cue, index, visual)
                for index, cue in enumerate(cues)
            ]
            output.append(TextCompositionBeat(beat_id=beat.id, items=items))
        return output

    def _layout_item(
        self,
        cue: TextCue,
        index: int,
        visual: CompositionBeat | None,
    ) -> TextLayoutItem:
        anchor = None
        if visual and cue.anchor_asset_id:
            anchor = next(
                (item for item in visual.items if item.asset_id == cue.anchor_asset_id),
                None,
            )

        if anchor is not None:
            x = self._clamp(anchor.x, 0.18, 0.82)
            if index % 2 == 0:
                y = self._clamp(anchor.y - anchor.height / 2 - 0.075, 0.10, 0.82)
                placement = "above_anchor"
            else:
                y = self._clamp(anchor.y + anchor.height / 2 + 0.075, 0.18, 0.90)
                placement = "below_anchor"
        else:
            x = 0.50
            y = self._clamp(0.16 + index * 0.10, 0.10, 0.84)
            placement = "safe_top"

        return TextLayoutItem(
            text_cue_id=cue.id,
            x=x,
            y=y,
            max_width=0.42 if cue.priority >= 85 else 0.36,
            z=50 + min(20, cue.priority // 5),
            anchor_asset_id=cue.anchor_asset_id,
            placement=placement,
        )

    @staticmethod
    def _clamp(value: float, low: float, high: float) -> float:
        return max(low, min(high, value))
