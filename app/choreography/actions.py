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


class SemanticActionResolver:
    """Infer visual action from package semantic metadata, not topic-specific scene IDs.

    The Final Package already carries stable machine-readable English semantic names and
    narrative functions. This resolver converts those generic concepts into a compact
    choreography vocabulary usable across future packages and languages.
    """

    _RULES: tuple[tuple[str, tuple[str, ...], float, float, float], ...] = (
        ("REJECT", ("reject", "decline", "insufficient", "not_allow", "denied", "fail"), 0.95, 0.95, 0.86),
        ("BLOCK", ("limit", "cap", "exceed", "gate", "restriction", "threshold"), 0.88, 0.88, 0.90),
        ("LOCK", ("reserve", "reserved", "hold", "locked", "installment"), 0.72, 0.72, 0.96),
        ("LOOP", ("retry", "repeat", "ten_retries", "again"), 0.76, 0.90, 0.82),
        ("PROTECT", ("privacy", "shield", "protect", "details"), 0.60, 0.64, 1.04),
        ("TRAVEL", ("request", "route", "reach", "send", "transmit", "payment_moment"), 0.62, 0.82, 0.94),
        ("SCAN", ("currency", "card", "value", "amount", "filter", "system"), 0.48, 0.66, 1.00),
        ("COMPARE", ("compare", "difference", "separate", "physical_store", "online", "international"), 0.58, 0.72, 1.02),
        ("RESOLVE", ("solution", "raise", "reduce", "second", "available_amount", "actual_available"), 0.28, 0.72, 1.08),
        ("REVEAL", ("show", "explain", "wallet", "balance", "available", "total"), 0.32, 0.58, 1.04),
    )

    def resolve(self, scene: SceneSource | None, beat: StoryBeat) -> ActionDecision:
        text_parts: list[str] = [beat.action, beat.narration]
        relationship: str | None = None
        labels: list[str] = []
        if scene is not None:
            text_parts.extend([scene.purpose or "", scene.visual_concept or "", scene.relation_to_previous or ""])
            for unit in scene.units:
                for key in ("semantic_name", "narrative_function", "semantic_intent", "relationship"):
                    value = str(unit.get(key) or "")
                    if value:
                        text_parts.append(value)
                semantic_name = str(unit.get("semantic_name") or "").strip()
                if semantic_name:
                    labels.append(semantic_name)
                if relationship is None and unit.get("relationship"):
                    relationship = str(unit["relationship"])

        corpus = self._normalize(" ".join(text_parts))
        for action, needles, tension, energy, pacing_bias in self._RULES:
            if any(needle in corpus for needle in needles):
                return ActionDecision(
                    action=action,
                    tension=tension,
                    energy=energy,
                    labels=tuple(labels),
                    relationship=relationship,
                    pacing_bias=pacing_bias,
                )

        return ActionDecision(
            action="FOCUS",
            tension=0.34,
            energy=0.56,
            labels=tuple(labels),
            relationship=relationship,
            pacing_bias=1.0,
        )

    @staticmethod
    def _normalize(value: str) -> str:
        value = value.casefold().replace("-", "_")
        return re.sub(r"[^\w\u0600-\u06ff]+", "_", value)
