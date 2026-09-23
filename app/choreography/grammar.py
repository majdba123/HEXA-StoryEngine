from __future__ import annotations

from app.models import StoryBeat

from .models import InteractionIntent, SequencePhase, VisualGrammarStage, VisualStateTransition


class ReferenceGrammarPlanner:
    """Encode the progressive visual grammar observed in accepted reference material.

    ENTER -> READ -> ADD -> RELATE -> RESULT -> RELEASE is not a rigid animation preset.
    It is an authoring grammar: each sequence should progressively construct meaning,
    rather than display a static poster or repeatedly wobble the same object.
    """

    def stages_for_beat(
        self,
        *,
        beat: StoryBeat,
        index: int,
        count: int,
        phase: SequencePhase,
        interaction: InteractionIntent | None,
        transitions: tuple[VisualStateTransition, ...],
    ) -> tuple[VisualGrammarStage, ...]:
        stages: list[VisualGrammarStage] = []
        if index == 0:
            stages.extend((VisualGrammarStage.ENTER, VisualGrammarStage.READ))
        elif phase in {
            SequencePhase.ACTION,
            SequencePhase.SETUP,
            SequencePhase.HANDOFF,
        }:
            # A handoff still introduces the next visual/narrative unit. Treating it
            # as RELEASE-only makes valid two-beat sequences fail the progressive
            # grammar contract even though the second beat clearly adds meaning.
            stages.append(VisualGrammarStage.ADD)

        if (
            interaction is not None
            and interaction.relationship
            and interaction.requires_state_change
        ):
            stages.append(VisualGrammarStage.RELATE)

        role = beat.semantic_context.story_role.upper() if beat.semantic_context else "CONTEXT"
        if phase == SequencePhase.CONSEQUENCE or role in {"CONSEQUENCE", "RESOLUTION"}:
            stages.append(VisualGrammarStage.RESULT)
        elif any(row.meaningful for row in transitions) and index > 0:
            stages.append(VisualGrammarStage.RESULT)

        if index == count - 1:
            stages.append(VisualGrammarStage.RELEASE)

        if not stages:
            stages.append(VisualGrammarStage.READ)
        return tuple(dict.fromkeys(stages))
