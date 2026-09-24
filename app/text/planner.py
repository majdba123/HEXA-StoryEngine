from __future__ import annotations

from app.choreography import ChoreographyDirective, ChoreographyPlan
from app.models import PackageModel, StoryBeat, TextCue, TextPlan, TextStyle, TextTokenCue, Transcript, VisualAsset
from app.text.semantic import KeywordCandidate, TextSemanticSelector
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
                anchor_asset_id = self._anchor_asset_id(
                    beat=beat,
                    candidate=candidate,
                    directive=directive,
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
                    priority=min(
                        100,
                        self._priority(candidate.semantic_type)
                        + max(0, round((candidate.score - 0.74) * 20)),
                    ),
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
    def _anchor_asset_id(
        *,
        beat: StoryBeat,
        candidate: KeywordCandidate,
        directive: ChoreographyDirective | None,
    ) -> str | None:
        """Resolve text to the exact Story asset span before beat-level fallback.

        Final Package/Story already owns canonical character spans for semantic assets.
        Text wording and spoken timing stay untouched; this only chooses WHICH visual
        receives the text relationship.
        """
        cue_start = int(candidate.source_char_start)
        cue_end = int(candidate.source_char_end)
        matches = []
        for activation in beat.asset_activations:
            start = activation.trigger_char_start
            end = activation.trigger_char_end
            if start is None or end is None or end <= start:
                continue
            overlap = max(0, min(cue_end, end) - max(cue_start, start))
            if overlap <= 0:
                continue
            cue_len = max(1, cue_end - cue_start)
            activation_len = max(1, end - start)
            visual_focus = str(activation.visual_focus or "").upper()
            focus_rank = {
                "RESULT": 0,
                "PRIMARY": 1,
                "SUPPORT": 2,
                "CONTEXT": 3,
            }.get(visual_focus, 2)
            matches.append((
                overlap / cue_len,
                overlap / activation_len,
                float(activation.confidence),
                -focus_rank,
                -activation_len,
                activation.asset_id,
            ))

        if matches:
            best_prefix = max(row[:-1] for row in matches)
            tied_ids = sorted(row[-1] for row in matches if row[:-1] == best_prefix)
            preferred = directive.primary_asset_id if directive is not None else None
            if preferred in tied_ids:
                return preferred
            for asset_id in beat.primary_asset_ids:
                if asset_id in tied_ids:
                    return asset_id
            return tied_ids[0]

        if directive is not None and directive.primary_asset_id:
            return directive.primary_asset_id
        return (beat.primary_asset_ids or [None])[0]

    @staticmethod
    def _priority(semantic_type: str) -> int:
        return {
            "warning_amount": 100,
            "warning": 95,
            "amount": 90,
            "number": 85,
            "emphasis": 75,
            "keyword": 60,
        }.get(semantic_type, 50)
