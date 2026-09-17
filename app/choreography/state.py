from __future__ import annotations

from app.models import StoryBeat

from .binding import AssetBinding
from .models import InteractionIntent, VisualStateTransition


class VisualStateCompiler:
    """Turn semantic interactions into explicit before/after visual states.

    States stay deliberately generic. They describe narrative change rather than domain
    facts, so the same contracts work for finance, commerce, health, education, or any
    other Final Package vocabulary.
    """

    _SUBJECT_STATES = {
        "REJECT": ("ATTEMPTING", "REJECTED"),
        "BLOCK": ("APPROACHING", "BLOCKED"),
        "LOCK": ("AVAILABLE", "LOCKED"),
        "LOOP": ("ATTEMPTING", "RETRYING"),
        "TRAVEL": ("SOURCE", "TRANSFERRED"),
        "COMPARE": ("BASELINE", "COMPARED"),
        "PROTECT": ("EXPOSED", "PROTECTED"),
        "RESOLVE": ("UNRESOLVED", "RESOLVED"),
        "REVEAL": ("CONCEALED", "REVEALED"),
        "REACT": ("NEUTRAL", "REACTING"),
        "CONNECT": ("SEPARATE", "CONNECTED"),
    }
    _OBJECT_STATES = {
        "REJECT": ("WAITING", "DECLINING"),
        "BLOCK": ("OPEN", "BLOCKING"),
        "LOCK": ("OPEN", "LOCKED"),
        "LOOP": ("WAITING", "RECEIVING_RETRY"),
        "TRAVEL": ("WAITING", "RECEIVED"),
        "COMPARE": ("BASELINE", "COMPARED"),
        "PROTECT": ("UNGUARDED", "GUARDED"),
        "RESOLVE": ("PROBLEM", "RESOLUTION_TARGET"),
        "REVEAL": ("CONTEXT", "EVIDENCE"),
        "REACT": ("TRIGGER", "OBSERVED"),
        "CONNECT": ("SEPARATE", "CONNECTED"),
    }

    def compile_all(
        self,
        beat: StoryBeat,
        binding: AssetBinding,
        action: str,
        interactions: tuple[InteractionIntent, ...],
    ) -> tuple[VisualStateTransition, ...]:
        context = beat.semantic_context
        output: list[VisualStateTransition] = []

        for interaction in interactions:
            if not interaction.requires_state_change:
                continue
            semantic_action = interaction.semantic_action or action
            if interaction.subject_asset_id:
                before, after = self._SUBJECT_STATES.get(
                    semantic_action, ("CONTEXT", "FOCUSED")
                )
                output.append(
                    VisualStateTransition(
                        asset_id=interaction.subject_asset_id,
                        from_state=before,
                        to_state=after,
                        reason=semantic_action,
                        semantic_unit_id=interaction.subject_unit_id,
                        confidence=interaction.confidence,
                        meaningful=semantic_action in self._SUBJECT_STATES,
                    )
                )
            if interaction.object_asset_id:
                before, after = self._OBJECT_STATES.get(
                    semantic_action, ("CONTEXT", "ENGAGED")
                )
                output.append(
                    VisualStateTransition(
                        asset_id=interaction.object_asset_id,
                        from_state=before,
                        to_state=after,
                        reason=interaction.relationship or semantic_action,
                        semantic_unit_id=interaction.object_unit_id,
                        confidence=interaction.confidence,
                        meaningful=semantic_action in self._OBJECT_STATES,
                    )
                )
            if interaction.result_asset_id:
                output.append(
                    VisualStateTransition(
                        asset_id=interaction.result_asset_id,
                        from_state="PENDING",
                        to_state="RESULT",
                        reason="RESULT",
                        semantic_unit_id=interaction.result_unit_id,
                        confidence=interaction.confidence,
                        meaningful=True,
                    )
                )

        if not output and binding.focus_asset_id:
            meaningful = action in {"REVEAL", "RESOLVE", "COMPARE", "PROTECT"}
            target_state = {
                "REVEAL": "REVEALED",
                "RESOLVE": "RESOLVED",
                "COMPARE": "COMPARED",
                "PROTECT": "PROTECTED",
            }.get(action, "FOCUSED")
            unit_id = None
            if context and context.subject_unit_ids:
                unit_id = context.subject_unit_ids[0]
            output.append(
                VisualStateTransition(
                    asset_id=binding.focus_asset_id,
                    from_state="CONTEXT",
                    to_state=target_state,
                    reason=action,
                    semantic_unit_id=unit_id,
                    confidence=binding.binding_confidence,
                    meaningful=meaningful,
                )
            )

        # Multiple package relations may reference the same asset. Preserve the strongest
        # meaningful transition, then confidence, so downstream layers get one coherent
        # state per asset without losing the relationship evidence stored on interactions.
        by_asset: dict[str, VisualStateTransition] = {}
        for row in output:
            previous = by_asset.get(row.asset_id)
            if previous is None:
                by_asset[row.asset_id] = row
                continue
            previous_rank = (1 if previous.meaningful else 0, previous.confidence)
            row_rank = (1 if row.meaningful else 0, row.confidence)
            if row_rank > previous_rank:
                by_asset[row.asset_id] = row
        return tuple(by_asset.values())

    def compile(
        self,
        beat: StoryBeat,
        binding: AssetBinding,
        action: str,
        interaction: InteractionIntent | None,
    ) -> tuple[VisualStateTransition, ...]:
        return self.compile_all(
            beat,
            binding,
            action,
            (interaction,) if interaction is not None else (),
        )
