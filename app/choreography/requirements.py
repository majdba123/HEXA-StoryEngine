from __future__ import annotations

from app.models import StoryBeat

from .binding import AssetBinding
from .models import AssetRequirement, InteractionIntent, ParticipantRole


class AssetRequirementCompiler:
    """Describe semantic assets Choreography needs without invoking another Cutout pass.

    The output is diagnostic only. Missing requirements are evidence for a future targeted
    refinement pass; they never cause broad re-segmentation or mutate current assets.
    """

    def compile_all(
        self,
        beat: StoryBeat,
        binding: AssetBinding,
        interactions: tuple[InteractionIntent, ...],
        action: str,
    ) -> tuple[AssetRequirement, ...]:
        context = beat.semantic_context
        if context is None:
            return ()
        mapped = dict(binding.semantic_asset_map)
        rows: list[AssetRequirement] = []

        def add(
            unit_id: str | None,
            role: ParticipantRole,
            reason: str,
            required_for_action: str,
        ) -> None:
            if not unit_id:
                return
            bound = mapped.get(unit_id)
            rows.append(
                AssetRequirement(
                    semantic_unit_id=unit_id,
                    participant_role=role,
                    reason=reason,
                    required_for_action=required_for_action,
                    satisfied=bound is not None,
                    bound_asset_id=bound,
                    confidence=binding.binding_confidence,
                )
            )

        meaningful_interactions = tuple(
            row
            for row in interactions
            if row.requires_state_change
            or row.authority == "FINAL_PACKAGE_INTERACTION_TARGET"
        )
        if meaningful_interactions:
            for interaction in meaningful_interactions:
                required_action = interaction.semantic_action or action
                add(
                    interaction.subject_unit_id,
                    ParticipantRole.SUBJECT,
                    "interaction_subject",
                    required_action,
                )
                add(
                    interaction.object_unit_id,
                    ParticipantRole.OBJECT,
                    "interaction_object",
                    required_action,
                )
                add(
                    interaction.result_unit_id,
                    ParticipantRole.RESULT,
                    "interaction_result",
                    required_action,
                )
        else:
            add(
                context.subject_unit_ids[0] if context.subject_unit_ids else None,
                ParticipantRole.SUBJECT,
                "story_subject",
                action,
            )

        deduped: dict[tuple[str, ParticipantRole, str], AssetRequirement] = {}
        for row in rows:
            deduped[(row.semantic_unit_id, row.participant_role, row.required_for_action)] = row
        return tuple(deduped.values())

    def compile(
        self,
        beat: StoryBeat,
        binding: AssetBinding,
        interaction: InteractionIntent | None,
        action: str,
    ) -> tuple[AssetRequirement, ...]:
        return self.compile_all(
            beat,
            binding,
            (interaction,) if interaction is not None else (),
            action,
        )
