from __future__ import annotations


_NO_AUTOMATIC_REACTION_ACTIONS = frozenset({"COMPARE", "LOOP"})


def relation_requires_reaction(
    *,
    semantic_action: str | None,
    executable: bool,
    target_asset_id: str | None,
    target_has_state_change: bool = False,
) -> bool:
    """Canonical visual-reaction contract for executable authored relations.

    Final Package relation semantics are authoritative. If an executable relation names
    a distinct target, Choreography must give that target a visible REACT phase unless
    the semantic action intentionally describes a balanced/non-causal relation such as
    COMPARE or LOOP. An authored target state transition may still request a reaction
    for those non-automatic actions.

    Keeping this rule shared with semantic Motion QA prevents a package from compiling
    under one reaction policy and then being rejected by a second, stricter validator.
    """
    if not executable or not target_asset_id:
        return False
    action = str(semantic_action or "").upper()
    if action in _NO_AUTOMATIC_REACTION_ACTIONS:
        return bool(target_has_state_change)
    return True
