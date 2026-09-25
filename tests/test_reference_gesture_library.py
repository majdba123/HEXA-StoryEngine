from __future__ import annotations

from app.models import LayoutItem
from app.motion.reference_gestures import ReferenceGestureLibrary
from app.reference.motion_language import ReferenceGestureKind, ReferenceMotionLanguage


def _item(x: float = 0.25) -> LayoutItem:
    return LayoutItem(asset_id="asset", x=x, y=0.5, width=0.25, height=0.30)


def _assert_holds_after_settle(program) -> None:
    tail = [frame for frame in program.keyframes if frame.progress >= program.settle_progress]
    assert tail
    assert all(abs(frame.dx) <= 1e-9 for frame in tail)
    assert all(abs(frame.dy) <= 1e-9 for frame in tail)
    assert all(abs(frame.scale - 1.0) <= 1e-9 for frame in tail)


def test_reference_entry_gestures_are_one_shot_then_hold() -> None:
    library = ReferenceGestureLibrary()
    for role, primary in (("SUBJECT", True), ("SUPPORT", False), ("RESULT", False)):
        program = library.build(
            action="REVEAL",
            item=_item(),
            index=0 if primary else 1,
            count=3,
            visual_duration=1.0,
            is_primary=primary,
            participant_role=role,
        )
        assert program.name.startswith("reference_")
        _assert_holds_after_settle(program)


def test_reference_payoff_is_bounded_result_enter_not_legacy_zoom() -> None:
    language = ReferenceMotionLanguage.production()
    gesture, _dx, _dy, scale = ReferenceGestureLibrary.event_accent(
        stage="PAYOFF",
        semantic_action="REVEAL",
        involvement="RESULT",
        vector=(0.05, 0.0),
        focus_strength=1.0,
    )
    assert gesture == ReferenceGestureKind.RESULT_ENTER
    assert scale <= language.max_result_scale
    assert scale < 1.05


def test_reference_reaction_changes_with_semantic_action() -> None:
    blocked = ReferenceGestureLibrary.event_accent(
        stage="REACT",
        semantic_action="BLOCK",
        involvement="TARGET",
        vector=(0.05, 0.0),
        focus_strength=1.0,
    )
    discovered = ReferenceGestureLibrary.event_accent(
        stage="REACT",
        semantic_action="REVEAL",
        involvement="TARGET",
        vector=(0.05, 0.0),
        focus_strength=1.0,
    )
    assert blocked[0] == ReferenceGestureKind.SHORT_IMPACT
    assert discovered[0] == ReferenceGestureKind.STATE_CHANGE
    assert blocked != discovered


def test_reference_fallback_actions_preserve_meaning_without_legacy_primitives() -> None:
    reject = ReferenceGestureLibrary.fallback_action_accent(
        action="REJECT",
        interaction_vector=(0.05, 0.0),
        focus_strength=1.0,
    )
    travel = ReferenceGestureLibrary.fallback_action_accent(
        action="TRAVEL",
        interaction_vector=(0.05, 0.0),
        focus_strength=1.0,
    )
    assert reject is not None and reject[0] == ReferenceGestureKind.SHORT_IMPACT
    assert travel is not None and travel[0] == ReferenceGestureKind.DIRECTIONAL_HANDOFF
