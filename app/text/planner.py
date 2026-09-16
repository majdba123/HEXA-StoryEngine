from __future__ import annotations

from app.models import StoryBeat, TextCue, TextPlan, TextStyle, Transcript, VisualAsset
from app.text.semantic import TextSemanticSelector
from app.text.style import TextStyleResolver
from app.text.timing import TextTimingPlanner


class TextPlanner:
    """Build sparse keyword text cues without changing the visual timing baseline."""

    def __init__(
        self,
        *,
        semantic: TextSemanticSelector | None = None,
        timing: TextTimingPlanner | None = None,
        style: TextStyleResolver | None = None,
    ) -> None:
        self.semantic = semantic or TextSemanticSelector()
        self.timing = timing or TextTimingPlanner()
        self.style = style or TextStyleResolver()

    def plan(
        self,
        *,
        transcript: Transcript,
        story: list[StoryBeat],
        assets: list[VisualAsset] | None = None,
    ) -> TextPlan:
        del assets  # Reserved for future semantic-to-asset matching; no hidden visual heuristics yet.
        cues: list[TextCue] = []
        styles: dict[str, TextStyle] = {}
        cue_number = 1

        for beat in story:
            candidates = self.semantic.select(beat, transcript)
            for candidate in candidates:
                timed = self.timing.align(candidate, transcript)
                if timed is None:
                    continue
                style = self.style.resolve(timed)
                styles[style.id] = style
                anchor_asset_id = (beat.primary_asset_ids or [None])[0]
                cues.append(TextCue(
                    id=f"text-{cue_number:03d}",
                    beat_id=beat.id,
                    text=candidate.display_text,
                    semantic_type=candidate.semantic_type,
                    source_char_start=candidate.source_char_start,
                    source_char_end=candidate.source_char_end,
                    spoken_start=timed.spoken_start,
                    spoken_end=timed.spoken_end,
                    emphasis_time=timed.emphasis_time,
                    anchor_asset_id=anchor_asset_id,
                    priority=self._priority(candidate.semantic_type),
                    style_id=style.id,
                    placement_hint="anchor",
                ))
                cue_number += 1

        return TextPlan(
            cues=sorted(cues, key=lambda cue: (cue.spoken_start, -cue.priority, cue.id)),
            styles=sorted(styles.values(), key=lambda style: style.id),
        )

    @staticmethod
    def _priority(semantic_type: str) -> int:
        return {
            "warning_amount": 100,
            "amount": 90,
            "number": 85,
            "emphasis": 75,
            "keyword": 60,
        }.get(semantic_type, 50)
