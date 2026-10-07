from __future__ import annotations

import re
from dataclasses import dataclass

from app.canonical import CanonicalScene
from app.models import StoryBeat, StorySemanticDiagnostic


@dataclass(frozen=True, slots=True)
class ActionDecision:
    action: str
    tension: float
    energy: float
    labels: tuple[str, ...]
    relationship: str | None
    pacing_bias: float = 1.0
    authority: str = "FALLBACK"
    diagnostics: tuple[StorySemanticDiagnostic, ...] = ()


class SemanticActionResolver:
    """Resolve a generic meaning-bearing visual action from Final Package semantics.

    Authority order is explicit relationship -> semantic intent/narrative function ->
    Story role -> compatibility vocabulary. Topic-specific nouns never outrank authored
    relationships or intents.
    """

    _RELATION_ACTIONS = {
        "rejects": "REJECT",
        "declines": "REJECT",
        "denies": "REJECT",
        "blocks": "BLOCK",
        "constrains": "BLOCK",
        "limits": "BLOCK",
        "reserves": "LOCK",
        "locks": "LOCK",
        "holds": "LOCK",
        "transfers_to": "TRAVEL",
        "sends_to": "TRAVEL",
        "moves_to": "TRAVEL",
        "flows_to": "TRAVEL",
        "receives": "TRAVEL",
        "reacts_to": "REACT",
        "reaction_to": "REACT",
        "compares_with": "COMPARE",
        "contrasts_with": "COMPARE",
        "protects": "PROTECT",
        "resolves": "RESOLVE",
        "reveals": "REVEAL",
        "produces": "REVEAL",
        "results_in": "REVEAL",
        "triggers": "REVEAL",
        "connects_to": "CONNECT",
        "links_to": "CONNECT",
        "attacks": "TRAVEL",
        "grants_access_to": "CONNECT",
        "creates": "REVEAL",
        "repairs": "RESOLVE",
        "reports_to": "TRAVEL",
        "authorizes": "CONNECT",
        "depends_on": "CONNECT",
        "enables": "CONNECT",
        "causes": "REVEAL",
        "causes_unused_security": "REVEAL",
        "leads_to": "REVEAL",
        "leads_to_discovery": "REVEAL",
        "reveals_identity": "REVEAL",
        "parallel_causes": "COMPARE",
        "withholds_disclosure": "BLOCK",
        "specifies": "REVEAL",
        "progresses_to": "REVEAL",
        "persists_over_time": "LOOP",
        "contains_risk": "REVEAL",
    }
    _INTENT_ACTIONS = (
        ("REJECT", ("reject", "decline", "deny", "fail")),
        ("BLOCK", ("block", "restrict", "constraint", "limit", "gate", "threshold")),
        ("LOCK", ("reserve", "hold", "lock")),
        ("LOOP", ("retry", "retries", "repeat", "again", "loop")),
        ("TRAVEL", ("transfer", "send", "route", "move", "travel", "flow")),
        ("COMPARE", ("compare", "contrast", "difference", "versus")),
        ("PROTECT", ("protect", "guard", "shield", "privacy")),
        ("RESOLVE", ("resolve", "solution", "remedy", "fix", "recover")),
        ("REACT", ("react", "reaction")),
        ("CONNECT", ("connect", "link", "associate")),
        ("REVEAL", ("reveal", "show", "explain", "introduce", "present")),
    )
    _COMPATIBILITY_RULES = (
        ("REJECT", ("insufficient", "not_allow", "denied")),
        ("BLOCK", ("cap", "exceed")),
        ("LOCK", ("reserved", "installment")),
        ("SCAN", ("scan", "inspect", "detect", "check")),
        ("RESOLVE", ("available_amount", "actual_available")),
    )

    _ACTION_PROFILE = {
        "REJECT": (0.95, 0.95, 0.86),
        "BLOCK": (0.88, 0.88, 0.90),
        "LOCK": (0.72, 0.72, 0.96),
        "LOOP": (0.76, 0.90, 0.82),
        "TRAVEL": (0.62, 0.82, 0.94),
        "COMPARE": (0.58, 0.72, 1.02),
        "PROTECT": (0.60, 0.64, 1.04),
        "RESOLVE": (0.28, 0.72, 1.08),
        "REACT": (0.66, 0.70, 0.98),
        "CONNECT": (0.45, 0.67, 1.00),
        "REVEAL": (0.32, 0.58, 1.04),
        "SCAN": (0.48, 0.66, 1.00),
        "FOCUS": (0.34, 0.56, 1.00),
    }

    def resolve(self, scene: CanonicalScene | None, beat: StoryBeat) -> ActionDecision:
        labels: list[str] = []
        relationships: list[str] = []
        primary_parts: list[str] = [beat.action]
        secondary_parts: list[str] = []
        context = beat.semantic_context
        contradictory_ids: set[str] = set()
        if scene is not None and not scene.semantic_events and not scene.relations:
            for unit in scene.units:
                if unit.priority_role_conflict:
                    contradictory_ids.add(unit.unit_id)

        if context is not None:
            primary_entities = [
                entity
                for entity in context.entities
                if str(entity.role or "").upper() == "PRIMARY"
                and entity.unit_id not in contradictory_ids
            ]
            if not primary_entities and context.entities:
                primary_entities = [
                    next((entity for entity in context.entities
                          if entity.unit_id not in contradictory_ids), context.entities[0])
                ]
            primary_ids = {entity.unit_id for entity in primary_entities}
            for entity in context.entities:
                if entity.unit_id in contradictory_ids:
                    continue
                values = (
                    entity.semantic_name,
                    entity.narrative_function,
                    entity.semantic_intent,
                )
                target = primary_parts if entity.unit_id in primary_ids else secondary_parts
                target.extend(value for value in values if value)
                if entity.semantic_name:
                    labels.append(entity.semantic_name)
            relationships.extend(relation.kind for relation in context.relations if relation.kind)

        if scene is not None:
            relationships.extend(
                relation.relation_type for relation in scene.relations
                if relation.relation_type and relation.relation_type not in relationships
            )
            primary_parts.extend([scene.purpose or "", scene.visual_concept or ""])
            has_declared_primary = any(
                str(unit.role or "").upper() == "PRIMARY" for unit in scene.units
            )
            for unit in scene.units:
                if unit.unit_id in contradictory_ids:
                    continue
                values = [
                    str(value or "")
                    for value in (
                        unit.semantic_name,
                        unit.narrative_function,
                        unit.semantic_intent,
                    )
                ]
                target = (
                    primary_parts
                    if (
                        str(unit.role or "").upper() == "PRIMARY"
                        or not has_declared_primary
                    )
                    else secondary_parts
                )
                target.extend(value for value in values if value)
                relationship = str(unit.relationship or "")
                if relationship:
                    relationships.append(relationship)
                semantic_name = str(unit.semantic_name or "").strip()
                if semantic_name and semantic_name not in labels:
                    labels.append(semantic_name)

        primary_corpus = self._normalize(" ".join(primary_parts))
        text_action = next((
            action for action, needles in self._INTENT_ACTIONS
            if any(needle in primary_corpus for needle in needles)
        ), None)

        # Only meaning-bearing/causal relationships may directly override the primary
        # concept. Descriptive relations such as EXPLAINS or CONTEXT_FOR remain useful
        # interaction evidence, but must not let a supporting character's generic
        # "reaction" metadata hijack the scene's authored primary meaning.
        for relationship in relationships:
            canonical = self._normalize(relationship).strip("_")
            action = self._RELATION_ACTIONS.get(canonical)
            if action:
                diagnostics: tuple[StorySemanticDiagnostic, ...] = ()
                if text_action and text_action != action:
                    matching_events = [
                        row.event_id for row in beat.event_authorities
                        if relationship in row.relation_kinds
                    ]
                    diagnostics = (StorySemanticDiagnostic(
                        scene_id=beat.scene_id, beat_id=beat.id,
                        event_id=matching_events[0] if len(matching_events) == 1 else None,
                        conflict_type="RELATION_TEXT_ACTION_CONFLICT",
                        authority_sources=["FINAL_PACKAGE_RELATION", "TEXT_INFERENCE"],
                        chosen_authority="FINAL_PACKAGE_RELATION",
                        source_values={"relation": relationship, "typed_action": action,
                                       "text_action": text_action},
                    ),)
                return self._decision(
                    action, labels, relationship, "FINAL_PACKAGE_RELATION",
                    diagnostics=diagnostics,
                )

        for action, needles in self._INTENT_ACTIONS:
            if any(needle in primary_corpus for needle in needles):
                return self._decision(
                    action,
                    labels,
                    relationships[0] if relationships else None,
                    "FINAL_PACKAGE_PRIMARY_SEMANTIC",
                )

        role = (context.story_role if context else "").upper()
        role_action = {
            "RESOLUTION": "RESOLVE",
            "COMPARISON": "COMPARE",
            "CONSEQUENCE": "REACT" if any(
                self._normalize(row).strip("_") in {"reacts_to", "reaction_to"}
                for row in relationships
            ) else "REVEAL",
            "ACTION": "TRAVEL" if relationships else "FOCUS",
            "COMPLICATION": "BLOCK" if relationships else "REVEAL",
            "SETUP": "REVEAL",
            "CONTEXT": "REVEAL",
        }.get(role)
        if role_action:
            return self._decision(
                role_action,
                labels,
                relationships[0] if relationships else None,
                "STORY_ROLE",
            )

        secondary_corpus = self._normalize(" ".join(secondary_parts))
        for action, needles in self._INTENT_ACTIONS:
            if any(needle in secondary_corpus for needle in needles):
                return self._decision(
                    action,
                    labels,
                    relationships[0] if relationships else None,
                    "FINAL_PACKAGE_SUPPORT_SEMANTIC",
                )

        compatibility_corpus = self._normalize(" ".join([beat.narration, *primary_parts]))
        for action, needles in self._COMPATIBILITY_RULES:
            if any(needle in compatibility_corpus for needle in needles):
                return self._decision(
                    action,
                    labels,
                    relationships[0] if relationships else None,
                    "COMPATIBILITY_HINT",
                )

        return self._decision(
            "FOCUS",
            labels,
            relationships[0] if relationships else None,
            "FALLBACK",
        )

    def _decision(
        self,
        action: str,
        labels: list[str],
        relationship: str | None,
        authority: str,
        diagnostics: tuple[StorySemanticDiagnostic, ...] = (),
    ) -> ActionDecision:
        tension, energy, pacing_bias = self._ACTION_PROFILE[action]
        return ActionDecision(
            action=action,
            tension=tension,
            energy=energy,
            labels=tuple(dict.fromkeys(labels)),
            relationship=relationship,
            pacing_bias=pacing_bias,
            authority=authority,
            diagnostics=diagnostics,
        )

    @staticmethod
    def _normalize(value: str) -> str:
        value = value.casefold().replace("-", "_")
        return re.sub(r"[^\w\u0600-\u06ff]+", "_", value)
