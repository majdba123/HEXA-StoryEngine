from __future__ import annotations

from app.models import StoryBeat, TextCompositionBeat, TextCue, TextMotionCue


class TextMotionPlanner:
    """Create text-only motion cues anchored to real spoken timestamps."""

    def plan(
        self,
        beats: list[StoryBeat],
        text_cues: list[TextCue],
        text_composition: list[TextCompositionBeat],
    ) -> list[TextMotionCue]:
        beat_ids = {beat.id for beat in beats}
        laid_out_ids = {
            item.text_cue_id
            for beat in text_composition
            for item in beat.items
        }
        output: list[TextMotionCue] = []
        for cue in text_cues:
            if cue.beat_id not in beat_ids or cue.id not in laid_out_ids:
                continue
            entrance_end = min(cue.spoken_end, cue.spoken_start + 0.22)
            entrance_end = max(cue.spoken_start + 0.05, entrance_end)
            output.append(TextMotionCue(
                beat_id=cue.beat_id,
                text_cue_id=cue.id,
                kind=self._kind(cue.semantic_type),
                start=cue.spoken_start,
                end=entrance_end,
                params={
                    "emphasis_time": cue.emphasis_time,
                    "spoken_end": cue.spoken_end,
                    "anchor_asset_id": cue.anchor_asset_id,
                },
            ))
        return output

    @staticmethod
    def _kind(semantic_type: str) -> str:
        if semantic_type == "warning_amount":
            return "text_warning_in"
        if semantic_type in {"amount", "number"}:
            return "text_number_in"
        if semantic_type == "emphasis":
            return "text_emphasis_in"
        return "text_keyword_in"
