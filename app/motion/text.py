from __future__ import annotations

from app.choreography import ChoreographyPlan
from app.models import (
    MotionCue,
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
        visual_motion: list[MotionCue] | None = None,
    ) -> list[TextMotionCue]:
        beat_by_id = {beat.id: beat for beat in beats}
        visual_by_anchor = {
            (cue.beat_id, cue.asset_id): cue
            for cue in (visual_motion or [])
        }
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
            anchor_motion = (
                visual_by_anchor.get((cue.beat_id, cue.anchor_asset_id))
                if cue.anchor_asset_id
                else None
            )
            sync = self._visual_sync_profile(cue, anchor_motion)

            visible_end = self.visibility.visible_end(
                cue,
                beat,
                cues_by_beat.get(cue.beat_id, []),
            )
            tokens = self._token_motion(
                cue,
                visible_end,
                action,
                first_duration=sync["entry_duration"],
            )
            entrance_end = tokens[0].end if tokens else min(
                cue.spoken_end,
                cue.spoken_start + self._entrance_duration(cue.semantic_type, 0),
            )
            entrance_end = max(cue.spoken_start + 0.05, entrance_end)
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
                        "entry_strength": sync["entry_strength"],
                        "entry_duration_ms": round(sync["entry_duration"] * 1000),
                        "visual_sync": {
                            "available": sync["available"],
                            "asset_id": cue.anchor_asset_id,
                            "semantic_settle": sync["semantic_settle"],
                            "focus_role": sync["focus_role"],
                            "cohort_role": sync["cohort_role"],
                            "cohort_gain": sync["cohort_gain"],
                        },
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
        *,
        first_duration: float | None = None,
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
            duration = (
                first_duration
                if index == 0 and first_duration is not None
                else self._entrance_duration(cue.semantic_type, index)
            )
            end = max(
                token.spoken_start + 0.05,
                min(token.spoken_start + duration, visible_end),
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
    def _visual_sync_profile(
        cue: TextCue,
        anchor_motion: MotionCue | None,
    ) -> dict[str, float | str | bool | None]:
        """Couple text emphasis to its visual anchor without moving text before speech."""
        default_duration = TextMotionPlanner._entrance_duration(cue.semantic_type, 0)
        if anchor_motion is None or not isinstance(anchor_motion.params, dict):
            return {
                "available": False,
                "entry_strength": 0.0,
                "entry_duration": default_duration,
                "semantic_settle": None,
                "focus_role": None,
                "cohort_role": None,
                "cohort_gain": 1.0,
            }

        focus = anchor_motion.params.get("semantic_focus") or {}
        if not isinstance(focus, dict):
            focus = {}
        role = str(focus.get("role") or "SUPPORT").upper()
        active = bool(focus.get("active"))
        raw_strength = focus.get("strength")
        try:
            authored_strength = (
                float(raw_strength) if raw_strength is not None else None
            )
        except (TypeError, ValueError):
            authored_strength = None
        if role == "RESULT":
            strength = 1.0
        elif authored_strength is not None:
            strength = authored_strength
        elif active:
            strength = 0.82
        elif role in {"SUBJECT", "OBJECT", "ACTOR"}:
            strength = 0.62
        elif role == "CONTEXT":
            strength = 0.20
        else:
            strength = 0.42

        # Text follows the same temporal attention hierarchy as its visual anchor. A
        # support/participant keyword must not hit as hard as the current Hero simply
        # because both are narration-aligned. Result peers remain intentionally strong.
        try:
            cohort_gain = float(focus.get("cohort_gain", 1.0))
        except (TypeError, ValueError):
            cohort_gain = 1.0
        cohort_gain = max(0.0, min(1.0, cohort_gain))
        cohort_role = str(focus.get("cohort_role") or "independent")
        if cohort_role == "result_peer":
            text_attention_gain = max(0.82, cohort_gain)
        elif cohort_role in {"leader", "leader_member", "independent"}:
            text_attention_gain = max(0.86, cohort_gain)
        elif cohort_role == "participant":
            text_attention_gain = min(0.76, 0.46 + cohort_gain * 0.45)
        elif cohort_role == "secondary":
            text_attention_gain = min(0.62, 0.38 + cohort_gain * 0.42)
        else:
            text_attention_gain = min(0.48, 0.28 + cohort_gain * 0.55)
        strength *= text_attention_gain

        raw_settle = anchor_motion.params.get("semantic_settle_time")
        try:
            semantic_settle = float(raw_settle) if raw_settle is not None else None
        except (TypeError, ValueError):
            semantic_settle = None

        duration = default_duration
        if semantic_settle is not None:
            delta = semantic_settle - cue.spoken_start
            if delta > 0:
                # The reference style is decisive rather than sluggish: use the anchor
                # settle as a synchronization target, but bound the text gesture so a
                # long spoken phrase never turns one keyword into a slow subtitle move.
                duration = max(0.13, min(0.24, delta))
        return {
            "available": True,
            "entry_strength": max(0.0, min(1.0, strength)),
            "entry_duration": duration,
            "semantic_settle": semantic_settle,
            "focus_role": role,
            "cohort_role": cohort_role,
            "cohort_gain": cohort_gain,
        }

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
