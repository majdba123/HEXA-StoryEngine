from __future__ import annotations

import re
from dataclasses import dataclass

from app.models import SceneSource, StoryBeat


@dataclass(frozen=True, slots=True)
class ActionDecision:
    action: str
    tension: float
    energy: float
    labels: tuple[str, ...]
    relationship: str | None
    pacing_bias: float = 1.0
    authority: str = "FALLBACK"


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

    def resolve(self, scene: SceneSource | None, beat: StoryBeat) -> ActionDecision:
        labels: list[str] = []
        relationships: list[str] = []
        primary_parts: list[str] = [beat.action]
        secondary_parts: list[str] = []
        context = beat.semantic_context

        if context is not None:
            primary_entities = [
                entity
                for entity in context.entities
                if str(entity.role or "").upper() == "PRIMARY"
            ]
            if not primary_entities and context.entities:
                primary_entities = [context.entities[0]]
            primary_ids = {entity.unit_id for entity in primary_entities}
            for entity in context.entities:
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
            primary_parts.extend([scene.purpose or "", scene.visual_concept or ""])
            has_declared_primary = any(
                str(unit.get("role") or "").upper() == "PRIMARY"
                for unit in scene.units
                if isinstance(unit, dict)
            )
            for unit in scene.units:
                values = [
                    str(unit.get(key) or "")
                    for key in ("semantic_name", "narrative_function", "semantic_intent")
                ]
                target = (
                    primary_parts
                    if (
                        str(unit.get("role") or "").upper() == "PRIMARY"
                        or not has_declared_primary
                    )
                    else secondary_parts
                )
                target.extend(value for value in values if value)
                relationship = str(unit.get("relationship") or "")
                if relationship:
                    relationships.append(relationship)
                semantic_name = str(unit.get("semantic_name") or "").strip()
                if semantic_name and semantic_name not in labels:
                    labels.append(semantic_name)

        # Only meaning-bearing/causal relationships may directly override the primary
        # concept. Descriptive relations such as EXPLAINS or CONTEXT_FOR remain useful
        # interaction evidence, but must not let a supporting character's generic
        # "reaction" metadata hijack the scene's authored primary meaning.
        for relationship in relationships:
            canonical = self._normalize(relationship).strip("_")
            action = self._RELATION_ACTIONS.get(canonical)
            if action:
                return self._decision(action, labels, relationship, "FINAL_PACKAGE_RELATION")

        primary_corpus = self._normalize(" ".join(primary_parts))
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
        )

    @staticmethod
    def _normalize(value: str) -> str:
        value = value.casefold().replace("-", "_")
        return re.sub(r"[^\w\u0600-\u06ff]+", "_", value)
