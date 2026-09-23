from __future__ import annotations

from app.choreography import ChoreographyPlan
from app.models import PackageModel, StoryBeat, TextCue, TextPlan, TextStyle, TextTokenCue, Transcript, VisualAsset
from app.text.semantic import TextSemanticSelector
from app.text.style import TextStyleResolver
from app.text.timing import TextTimingPlanner


class TextPlanner:
    """Build sparse narration-locked text cues from Story + Final Package semantics.

    Text remains an independent layer. Choreography may provide semantic synchronization
    and anchor choice, but it never owns the wording or forced-aligned timing.
    """

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
        package: PackageModel | None = None,
        choreography: ChoreographyPlan | None = None,
    ) -> TextPlan:
        del assets
        scene_by_id = {scene.id: scene for scene in package.scenes} if package else {}
        cues: list[TextCue] = []
        styles: dict[str, TextStyle] = {}
        cue_number = 1

        for beat in story:
            directive = choreography.for_beat(beat.id) if choreography else None
            context = beat.semantic_context
            scene = scene_by_id.get(beat.scene_id)
            candidates = self.semantic.select(beat, transcript, package=package)
            for candidate in candidates:
                timed = self.timing.align(candidate, transcript)
                if timed is None:
                    continue
                style = self.style.resolve(timed)
                styles[style.id] = style
                default_anchor_asset_id = (
                    directive.primary_asset_id
                    if directive is not None and directive.primary_asset_id
                    else (beat.primary_asset_ids or [None])[0]
                )
                anchor_asset_id = self._semantic_anchor(
                    beat,
                    source_char_start=candidate.source_char_start,
                    source_char_end=candidate.source_char_end,
                    default=default_anchor_asset_id,
                )
                package_evidence = list(context.evidence) if context else []
                if scene and scene.relation_to_previous:
                    package_evidence.append(f"scene_relation:{scene.relation_to_previous}")
                relationship = directive.relationship if directive is not None else None
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
                    priority=self._priority(candidate.semantic_type, candidate.score),
                    style_id=style.id,
                    placement_hint="anchor",
                    story_role=context.story_role if context else None,
                    choreography_action=directive.action if directive is not None else None,
                    semantic_unit_ids=list(directive.semantic_unit_ids) if directive is not None else [],
                    relationship=relationship,
                    package_evidence=list(dict.fromkeys(package_evidence)),
                    tokens=[
                        TextTokenCue(
                            text=token.display_text,
                            source_char_start=token.source_char_start,
                            source_char_end=token.source_char_end,
                            spoken_start=token.spoken_start,
                            spoken_end=token.spoken_end,
                        )
                        for token in timed.tokens
                    ],
                ))
                cue_number += 1

        return TextPlan(
            cues=sorted(cues, key=lambda cue: (cue.spoken_start, -cue.priority, cue.id)),
            styles=sorted(styles.values(), key=lambda style: style.id),
        )

    @staticmethod
    def _semantic_anchor(
        beat: StoryBeat,
        *,
        source_char_start: int,
        source_char_end: int,
        default: str | None,
    ) -> str | None:
        candidates = []
        for activation in beat.asset_activations:
            if activation.policy == "FALLBACK":
                continue
            if activation.trigger_char_start is None or activation.trigger_char_end is None:
                continue
            overlap = max(
                0,
                min(source_char_end, activation.trigger_char_end)
                - max(source_char_start, activation.trigger_char_start),
            )
            if overlap <= 0:
                continue
            candidates.append((
                overlap,
                activation.policy == "EXPLICIT",
                activation.confidence,
                -(activation.sequence_order or 10_000),
                activation.asset_id,
            ))
        if not candidates:
            return default
        candidates.sort(reverse=True)
        return candidates[0][-1]

    @staticmethod
    def _priority(semantic_type: str, score: float = 0.74) -> int:
        base = {
            "warning_amount": 100,
            "warning": 95,
            "amount": 90,
            "number": 85,
            "emphasis": 75,
            "keyword": 60,
        }.get(semantic_type, 50)
        semantic_bonus = round(max(-4.0, min(10.0, (score - 0.74) * 24.0)))
        return max(1, min(100, base + semantic_bonus))
