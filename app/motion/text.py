from __future__ import annotations

from app.choreography import ChoreographyPlan
from app.models import (
    StoryBeat,
    TextCompositionBeat,
    TextCue,
    TextMotionCue,
    TextMotionToken,
)
from app.text.timing.visibility import TextVisibilityPolicy


class TextMotionPlanner:
    """Plan text as a narration-locked but choreography-aware storytelling layer."""

    def __init__(self) -> None:
        self.visibility = TextVisibilityPolicy()

    def plan(
        self,
        beats: list[StoryBeat],
        text_cues: list[TextCue],
        text_composition: list[TextCompositionBeat],
        choreography: ChoreographyPlan | None = None,
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
            directive = choreography.for_beat(cue.beat_id) if choreography else None
            action = directive.action if directive is not None else cue.choreography_action

            visible_end = self.visibility.visible_end(
                cue,
                beat,
                cues_by_beat.get(cue.beat_id, []),
            )
            tokens = self._token_motion(cue, visible_end, action)
            entrance_end = tokens[0].end if tokens else min(
                visible_end,
                cue.spoken_end,
                cue.spoken_start + self._entrance_duration(cue.semantic_type, 0),
            )
            entrance_end = min(
                visible_end,
                max(cue.spoken_start + 0.03, entrance_end),
            )
            output.append(
                TextMotionCue(
                    beat_id=cue.beat_id,
                    text_cue_id=cue.id,
                    kind=self._kind(cue.semantic_type, action),
                    start=cue.spoken_start,
                    end=entrance_end,
                    params={
                        "emphasis_time": cue.emphasis_time,
                        "spoken_end": cue.spoken_end,
                        "visible_end": visible_end,
                        "anchor_asset_id": cue.anchor_asset_id,
                        "reveal_mode": "sequential_words",
                        "story_role": cue.story_role,
                        "choreography_action": action,
                        "semantic_unit_ids": cue.semantic_unit_ids,
                        "relationship": cue.relationship,
                        "package_evidence": cue.package_evidence,
                        "hook": directive.hook.value if directive is not None else "NONE",
                        "hook_mechanism": directive.hook_mechanism.value if directive is not None else "NONE",
                    },
                    tokens=tokens,
                )
            )
        return output

    def _token_motion(
        self,
        cue: TextCue,
        visible_end: float,
        action: str | None,
    ) -> list[TextMotionToken]:
        source_tokens = cue.tokens
        if not source_tokens:
            return [
                TextMotionToken(
                    text=cue.text,
                    start=cue.spoken_start,
                    end=max(
                        cue.spoken_start + 0.05,
                        min(cue.spoken_end, cue.spoken_start + 0.20),
                    ),
                    visible_end=visible_end,
                    kind=self._token_kind(cue.semantic_type, 0, action),
                )
            ]

        output: list[TextMotionToken] = []
        for index, token in enumerate(source_tokens):
            duration = self._entrance_duration(cue.semantic_type, index)
            end = min(
                visible_end,
                max(
                    token.spoken_start + 0.03,
                    min(token.spoken_start + duration, visible_end),
                ),
            )
            output.append(
                TextMotionToken(
                    text=token.text,
                    start=token.spoken_start,
                    end=end,
                    visible_end=visible_end,
                    kind=self._token_kind(cue.semantic_type, index, action),
                )
            )
        return output

    @staticmethod
    def _entrance_duration(semantic_type: str, index: int) -> float:
        base = 0.20 if semantic_type in {"warning_amount", "warning", "amount", "number"} else 0.17
        return max(0.13, base - min(index, 2) * 0.025)

    @staticmethod
    def _token_kind(semantic_type: str, index: int, action: str | None) -> str:
        action = str(action or "").upper()
        if action in {"REJECT", "BLOCK"}:
            return "text_word_result_hit_in" if index == 0 else "text_word_result_follow_in"
        if action in {"TRAVEL", "CONNECT"}:
            return "text_word_transfer_in" if index == 0 else "text_word_follow_in"
        if action in {"RESOLVE", "REVEAL"}:
            return "text_word_reveal_in" if index == 0 else "text_word_follow_in"
        if semantic_type in {"warning_amount", "warning"}:
            return "text_word_warning_in" if index else "text_word_warning_primary_in"
        if semantic_type in {"amount", "number"}:
            return "text_word_number_in" if index else "text_word_number_primary_in"
        return "text_word_follow_in" if index else "text_word_primary_in"

    @staticmethod
    def _kind(semantic_type: str, action: str | None) -> str:
        action = str(action or "").upper()
        if action in {"REJECT", "BLOCK"}:
            return "text_result_hit_in"
        if action in {"TRAVEL", "CONNECT"}:
            return "text_transfer_in"
        if action in {"RESOLVE", "REVEAL"}:
            return "text_story_reveal_in"
        if semantic_type in {"warning_amount", "warning"}:
            return "text_warning_in"
        if semantic_type in {"amount", "number"}:
            return "text_number_in"
        if semantic_type == "emphasis":
            return "text_emphasis_in"
        return "text_keyword_in"
