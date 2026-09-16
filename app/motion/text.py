from __future__ import annotations

from app.models import StoryBeat, TextCompositionBeat, TextCue, TextMotionCue


class TextMotionPlanner:
    """Create sparse text motion locked to spoken entry with readability-aware holds."""

    def plan(
        self,
        beats: list[StoryBeat],
        text_cues: list[TextCue],
        text_composition: list[TextCompositionBeat],
    ) -> list[TextMotionCue]:
        beat_by_id = {beat.id: beat for beat in beats}
        laid_out_ids = {
            item.text_cue_id
            for beat in text_composition
            for item in beat.items
        }
        cues_by_beat: dict[str, list[TextCue]] = {}
        for cue in text_cues:
            cues_by_beat.setdefault(cue.beat_id, []).append(cue)
        for rows in cues_by_beat.values():
            rows.sort(key=lambda row: (row.spoken_start, row.id))

        output: list[TextMotionCue] = []
        for cue in text_cues:
            beat = beat_by_id.get(cue.beat_id)
            if beat is None or cue.id not in laid_out_ids:
                continue
            entrance_end = min(cue.spoken_end, cue.spoken_start + self._entrance_duration(cue))
            entrance_end = max(cue.spoken_start + 0.05, entrance_end)
            visible_end = self._visible_end(cue, beat, cues_by_beat.get(cue.beat_id, []))
            output.append(TextMotionCue(
                beat_id=cue.beat_id,
                text_cue_id=cue.id,
                kind=self._kind(cue.semantic_type),
                start=cue.spoken_start,
                end=entrance_end,
                params={
                    "emphasis_time": cue.emphasis_time,
                    "spoken_end": cue.spoken_end,
                    "visible_end": visible_end,
                    "anchor_asset_id": cue.anchor_asset_id,
                },
            ))
        return output

    @staticmethod
    def _entrance_duration(cue: TextCue) -> float:
        if cue.semantic_type == "warning_amount":
            return 0.24
        if cue.semantic_type in {"amount", "number"}:
            return 0.20
        return 0.18

    @staticmethod
    def _visible_end(cue: TextCue, beat: StoryBeat, siblings: list[TextCue]) -> float:
        # Entry is exact Forced Alignment. Hold/exit are readability decisions derived
        # from text length and the next semantic cue, never used to shift sync anchors.
        min_read = min(1.65, max(0.70, 0.42 + len(cue.text) * 0.055))
        target = max(cue.spoken_end + 0.18, cue.spoken_start + min_read)
        later = [row.spoken_start for row in siblings if row.spoken_start > cue.spoken_start + 0.04]
        if later:
            target = min(target, max(cue.spoken_end, min(later) - 0.06))
        return min(beat.end, max(cue.spoken_end, target))

    @staticmethod
    def _kind(semantic_type: str) -> str:
        if semantic_type == "warning_amount":
            return "text_warning_in"
        if semantic_type in {"amount", "number"}:
            return "text_number_in"
        if semantic_type == "emphasis":
            return "text_emphasis_in"
        return "text_keyword_in"
