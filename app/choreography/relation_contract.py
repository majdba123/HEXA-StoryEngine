from __future__ import annotations

from enum import Enum
from typing import Any


SEMANTIC_PROXY_AUTHORITIES = frozenset({
    "FINAL_PACKAGE_COMPOUND_PROXY",
    "FINAL_PACKAGE_GROUP_PROXY",
})


_AUTOMATIC_REACTION_ACTIONS = frozenset({
    "REJECT",
    "BLOCK",
    "LOCK",
    "TRAVEL",
    "REACT",
    "CONNECT",
    "PROTECT",
    "RESOLVE",
})


class RelationTimingMode(str, Enum):
    """Temporal contract for an authored source -> target visual relation."""

    OVERLAP_REQUIRED = "OVERLAP_REQUIRED"
    SEQUENTIAL_ALLOWED = "SEQUENTIAL_ALLOWED"


def relation_requires_reaction(
    *,
    semantic_action: str | None,
    executable: bool,
    target_asset_id: str | None,
    target_has_state_change: bool = False,
) -> bool:
    """Canonical visual-reaction contract for executable authored relations.

    Final Package relation semantics are authoritative, but a named target does not by
    itself justify a second visual accent. Actions that physically/causally act on a
    co-present target require REACT. REVEAL-style relations instead let the target's own
    ESTABLISH/ADD or an authored PAYOFF express the evidence/result; forcing an extra
    REACT there creates duplicate motion and can contradict Story order.

    A truly authored target state change may still request REACT even for an otherwise
    non-automatic action. Keeping this rule shared by EventFlow, Motion and QA prevents
    producer/validator disagreement.
    """
    if not executable or not target_asset_id:
        return False
    action = str(semantic_action or "").upper()
    return action in _AUTOMATIC_REACTION_ACTIONS or bool(target_has_state_change)


def relation_timing_mode(
    *,
    source_activation: Any | None,
    target_activation: Any | None,
) -> RelationTimingMode:
    """Return whether target REACT must overlap SOURCE INTERACT.

    Story/Final-Package timing authority decides this contract. Assets in the same
    authored semantic event are co-present and keep the strict overlap contract. When
    the target belongs to a later authored semantic event, the relation is an ordered
    handoff/reveal/result and forcing overlap would rewrite Story authority.

    Script anchors and spoken windows are secondary fallbacks when event metadata is
    incomplete.
    Missing/ambiguous timing remains conservative: require overlap rather than guessing a
    sequential semantic relationship.
    """
    if source_activation is None or target_activation is None:
        return RelationTimingMode.OVERLAP_REQUIRED

    source_event_id = getattr(source_activation, "semantic_event_id", None)
    target_event_id = getattr(target_activation, "semantic_event_id", None)
    source_event_order = getattr(source_activation, "semantic_event_order", None)
    target_event_order = getattr(target_activation, "semantic_event_order", None)
    if source_event_id and target_event_id:
        if source_event_id == target_event_id:
            return RelationTimingMode.OVERLAP_REQUIRED
        if (
            isinstance(source_event_order, int)
            and isinstance(target_event_order, int)
            and target_event_order > source_event_order
        ):
            return RelationTimingMode.SEQUENTIAL_ALLOWED

    source_char_start = getattr(source_activation, "trigger_char_start", None)
    source_char_end = getattr(source_activation, "trigger_char_end", None)
    target_char_start = getattr(target_activation, "trigger_char_start", None)
    target_char_end = getattr(target_activation, "trigger_char_end", None)
    if all(
        isinstance(value, int)
        for value in (source_char_start, source_char_end, target_char_start, target_char_end)
    ):
        if source_char_start <= source_char_end and target_char_start <= target_char_end:
            if target_char_start >= source_char_end:
                return RelationTimingMode.SEQUENTIAL_ALLOWED
            return RelationTimingMode.OVERLAP_REQUIRED

    source_start = getattr(source_activation, "spoken_start", None)
    source_end = getattr(source_activation, "spoken_end", None)
    target_start = getattr(target_activation, "spoken_start", None)
    target_end = getattr(target_activation, "spoken_end", None)
    if all(
        isinstance(value, (int, float)) and not isinstance(value, bool)
        for value in (source_start, source_end, target_start, target_end)
    ):
        if source_start <= source_end and target_start <= target_end:
            # Keep a small tolerance for forced-alignment frame/word-boundary jitter.
            if target_start >= source_end + 0.02:
                return RelationTimingMode.SEQUENTIAL_ALLOWED

    return RelationTimingMode.OVERLAP_REQUIRED
