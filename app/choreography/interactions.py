from __future__ import annotations

from dataclasses import dataclass

from app.models import StoryBeat

from .actions import ActionDecision
from .binding import AssetBinding
from .models import InteractionIntent


_RELATION_ACTIONS = {
    "REJECTS": "REJECT",
    "DECLINES": "REJECT",
    "DENIES": "REJECT",
    "BLOCKS": "BLOCK",
    "CONSTRAINS": "BLOCK",
    "LIMITS": "BLOCK",
    "RESERVES": "LOCK",
    "LOCKS": "LOCK",
    "HOLDS": "LOCK",
    "TRANSFERS_TO": "TRAVEL",
    "SENDS_TO": "TRAVEL",
    "MOVES_TO": "TRAVEL",
    "FLOWS_TO": "TRAVEL",
    "REACTS_TO": "REACT",
    "REACTION_TO": "REACT",
    "COMPARES_WITH": "COMPARE",
    "CONTRASTS_WITH": "COMPARE",
    "PROTECTS": "PROTECT",
    "RESOLVES": "RESOLVE",
    "REVEALS": "REVEAL",
    "PRODUCES": "REVEAL",
    "RESULTS_IN": "REVEAL",
    "TRIGGERS": "REVEAL",
    "RECEIVES": "TRAVEL",
    "CONNECTS_TO": "CONNECT",
    "LINKS_TO": "CONNECT",
    "ATTACKS": "TRAVEL",
    "GRANTS_ACCESS_TO": "CONNECT",
    "CREATES": "REVEAL",
    "REPAIRS": "RESOLVE",
    "REPORTS_TO": "TRAVEL",
    "AUTHORIZES": "CONNECT",
    "DEPENDS_ON": "CONNECT",
    "ENABLES": "CONNECT",
    "CAUSES": "REVEAL",
    "CAUSES_UNUSED_SECURITY": "REVEAL",
    "LEADS_TO": "REVEAL",
    "LEADS_TO_DISCOVERY": "REVEAL",
    "REVEALS_IDENTITY": "REVEAL",
    "PARALLEL_CAUSES": "COMPARE",
    "WITHHOLDS_DISCLOSURE": "BLOCK",
    "SPECIFIES": "REVEAL",
    "PROGRESSES_TO": "REVEAL",
    "PERSISTS_OVER_TIME": "LOOP",
    "CONTAINS_RISK": "REVEAL",
    # Descriptive package relations still carry interaction meaning, but they do not
    # override a stronger primary semantic action in SemanticActionResolver.
    "EXPLAINS": "REVEAL",
    "CONTEXT_FOR": "REVEAL",
    "SUPPORTS": "REVEAL",
}

_MEANING_ACTIONS = {
    "REJECT",
    "BLOCK",
    "LOCK",
    "LOOP",
    "TRAVEL",
    "COMPARE",
    "PROTECT",
    "RESOLVE",
    "REVEAL",
    "REACT",
    "CONNECT",
}

# These relations describe a guide/context actor pointing toward a concept. The concept
# should remain the focal visual; the actor is a participant, not the thing being taught.
_OBJECT_FOCUS_RELATIONS = {"EXPLAINS", "CONTEXT_FOR", "SUPPORTS", "SPECIFIES"}
_NON_EXECUTABLE_RELATIONS = {"SPECIFIES"}


@dataclass(frozen=True, slots=True)
class InteractionCompiler:
    """Compile Story semantics into conservative executable interaction intents.

    Every explicit Final Package relationship is preserved. A single primary interaction
    is selected later by Choreography for execution so the visual does not become noisy,
    but no authored relationship is silently dropped from downstream metadata/QA.
    """

    def compile_all(
        self,
        beat: StoryBeat,
        binding: AssetBinding,
        decision: ActionDecision,
    ) -> tuple[InteractionIntent, ...]:
        context = beat.semantic_context
        unit_map = dict(binding.semantic_asset_map)
        fallback_result_unit = (
            context.result_unit_ids[0]
            if context and context.result_unit_ids
            else None
        )

        relations = list(context.relations) if context else []
        relations.sort(
            key=lambda row: (
                0 if row.authority == "FINAL_PACKAGE_INTERACTION_TARGET" else 1,
                0 if row.causal else 1,
                -row.confidence,
                row.source_unit_id,
                row.target_unit_id,
                row.kind,
            )
        )
        compiled: list[InteractionIntent] = []
        for relation in relations:
            subject_asset = unit_map.get(relation.source_unit_id)
            object_asset = unit_map.get(relation.target_unit_id)
            # Relation-level result authority is explicit only. A semantic event may
            # independently own RESULT assets, but borrowing one here would fabricate
            # a causal payoff for relations such as COMPARE/CONTRAST that authored no
            # result. Event-flow PAYOFF still comes from the event's RESULT role.
            result_unit = relation.result_unit_id
            result_asset = unit_map.get(result_unit) if result_unit else None
            canonical = self._canonical(relation.kind)
            relation_action = _RELATION_ACTIONS.get(canonical)
            action = (
                decision.action
                if canonical in _OBJECT_FOCUS_RELATIONS and decision.action in _MEANING_ACTIONS
                else relation_action or decision.action
            )
            distinct = bool(subject_asset and object_asset and subject_asset != object_asset)
            is_progression = relation.authority == "FINAL_PACKAGE_VISUAL_PROGRESSION"
            executable_relation = (
                distinct
                and not is_progression
                and canonical not in _NON_EXECUTABLE_RELATIONS
            )
            compiled.append(
                InteractionIntent(
                    semantic_action=action,
                    relationship=relation.kind,
                    subject_asset_id=subject_asset,
                    object_asset_id=object_asset,
                    result_asset_id=result_asset,
                    subject_unit_id=relation.source_unit_id,
                    object_unit_id=relation.target_unit_id,
                    result_unit_id=result_unit,
                    authority=relation.authority,
                    confidence=min(1.0, relation.confidence * binding.binding_confidence),
                    executable=executable_relation,
                    requires_state_change=(
                        executable_relation and action in _MEANING_ACTIONS
                    ),
                    trigger_char_start=relation.trigger_char_start,
                    trigger_char_end=relation.trigger_char_end,
                    spoken_start=relation.spoken_start,
                    spoken_end=relation.spoken_end,
                    evidence=tuple((context.evidence if context else [])[:8]),
                )
            )

        if compiled:
            return tuple(compiled)

        if decision.action not in _MEANING_ACTIONS:
            return ()
        result_unit = fallback_result_unit
        result_asset = unit_map.get(result_unit) if result_unit else None
        subject_asset = binding.focus_asset_id
        object_asset = binding.interaction_asset_id
        if not subject_asset:
            return ()
        distinct = bool(object_asset and object_asset != subject_asset)
        subject_unit = context.subject_unit_ids[0] if context and context.subject_unit_ids else None
        object_unit = context.object_unit_ids[0] if context and context.object_unit_ids else None
        return (
            InteractionIntent(
                semantic_action=decision.action,
                relationship=decision.relationship,
                subject_asset_id=subject_asset,
                object_asset_id=object_asset,
                result_asset_id=result_asset,
                subject_unit_id=subject_unit,
                object_unit_id=object_unit,
                result_unit_id=result_unit,
                authority="CHOREOGRAPHY_ACTION_FALLBACK",
                confidence=0.62 * binding.binding_confidence,
                executable=distinct,
                requires_state_change=decision.action in _MEANING_ACTIONS,
                evidence=tuple((context.evidence if context else [])[:8]),
            ),
        )

    def compile(
        self,
        beat: StoryBeat,
        binding: AssetBinding,
        decision: ActionDecision,
    ) -> InteractionIntent | None:
        interactions = self.compile_all(beat, binding, decision)
        return self.primary(interactions, binding)

    @classmethod
    def primary(
        cls,
        interactions: tuple[InteractionIntent, ...],
        binding: AssetBinding,
    ) -> InteractionIntent | None:
        if not interactions:
            return None
        focus = binding.focus_asset_id

        def score(row: InteractionIntent) -> tuple[int, int, int, float, int]:
            canonical = cls._canonical(row.relationship)
            descriptive = canonical in _OBJECT_FOCUS_RELATIONS
            focal_participates = focus in row.participant_asset_ids if focus else False
            authority_rank = {
                "FINAL_PACKAGE_ASSET_RELATION": 4,
                "FINAL_PACKAGE_INTERACTION_TARGET": 3,
                "CHOREOGRAPHY_ACTION_FALLBACK": 2,
                "FINAL_PACKAGE_VISUAL_PROGRESSION": 1,
            }.get(row.authority, 0)
            return (
                authority_rank,
                1 if row.executable else 0,
                0 if descriptive else 1,
                row.confidence,
                1 if focal_participates else 0,
            )

        return max(interactions, key=score)

    @classmethod
    def preferred_focus(
        cls,
        interaction: InteractionIntent | None,
        binding: AssetBinding,
    ) -> str | None:
        if interaction is None:
            return binding.focus_asset_id
        canonical = cls._canonical(interaction.relationship)
        if canonical in _OBJECT_FOCUS_RELATIONS:
            return interaction.object_asset_id or binding.focus_asset_id
        if interaction.semantic_action == "REACT":
            return interaction.subject_asset_id or binding.focus_asset_id
        return interaction.subject_asset_id or binding.focus_asset_id

    @staticmethod
    def _canonical(value: str | None) -> str:
        return str(value or "").strip().upper().replace("-", "_").replace(" ", "_")