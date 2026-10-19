"""Production regression for Black Hat's scene-36 resolving icon.

The user's real export failed only after the YouTube video was encoded. The
authored PAYOFF program reached 0.01188 normalized activity versus the shared
0.01340 semantic floor. This test enforces the SAME floor at Motion authoring.
"""
from __future__ import annotations

from math import hypot

import pytest

from app.choreography import EventFlowStage
from app.models import LayoutItem, MotionSegment
from app.motion.event_flow import MotionEventPhase
from app.motion.planner import MotionPlanner
from app.motion.timing import semantic_readability_floor
from app.render.verification import EncodedMotionVerifier


def _payoff() -> MotionEventPhase:
    return MotionEventPhase(
        event_id="black-hat-scene-36-payoff", event_order=0,
        stage=EventFlowStage.PAYOFF, step_index=0, involvement="RESULT",
        focus_asset_id="SCENE_036:asset-04", source_asset_id=None,
        target_asset_id=None, result_asset_id="SCENE_036:asset-04",
        relationship=None, semantic_action="REVEAL", authority="EXPLICIT",
    )


def test_real_black_hat_036_payoff_scale_reaches_shared_readability_floor() -> None:
    item = LayoutItem(asset_id="SCENE_036:asset-04", x=0.5, y=0.5,
                      width=0.1584, height=0.16)
    duration, readability = 0.42, 0.201
    floor = semantic_readability_floor(
        "PAYOFF", item_width=item.width, item_height=item.height,
        duration=readability)
    assert floor == pytest.approx(0.01340, abs=1e-7)
    assert 0.075 * min(item.width, item.height) == pytest.approx(0.01188, abs=1e-7)
    dx, dy, scale = MotionPlanner._enforce_event_readability(
        phase=_payoff(), item=item, dx=0.0, dy=0.0, scale=1.0,
        duration=duration, readability_duration=readability)
    assert dx == dy == 0.0, "Prefer a clear icon pop rather than a lateral PAYOFF shake"
    assert 1.075 < scale <= 1.095
    activity = max(hypot(dx, dy), abs(scale - 1.0) * min(item.width, item.height))
    assert activity >= floor

    # Independently exercise the actual encoded verifier's Composition-space
    # activity measurement, not just a mirror of the planner's own formula.
    segment = MotionSegment(phase="PAYOFF", start=1.0, end=1.42,
                            program={"name": "reference_payoff", "keyframes": [
                                {"progress": 0.0, "dx": 0.0, "dy": 0.0, "scale": 1.0},
                                {"progress": 0.618034, "dx": round(dx, 6),
                                 "dy": round(dy, 6), "scale": round(scale, 6)},
                                {"progress": 1.0, "dx": 0.0, "dy": 0.0, "scale": 1.0}]})
    assert EncodedMotionVerifier._expected_activity_normalized(
        segment, item_width=item.width, item_height=item.height) >= floor


def test_tiny_payoff_uses_upward_not_sideways_fallback_if_scale_is_insufficient() -> None:
    item = LayoutItem(asset_id="tiny-result", x=0.5, y=0.5, width=0.08, height=0.08)
    floor = semantic_readability_floor(
        "PAYOFF", item_width=item.width, item_height=item.height, duration=0.201)
    dx, dy, scale = MotionPlanner._enforce_event_readability(
        phase=_payoff(), item=item, dx=0.0, dy=0.0, scale=1.0,
        duration=0.42, readability_duration=0.201)
    assert dx == 0.0
    assert dy < 0
    assert max(hypot(dx, dy), abs(scale - 1.0) * item.width) >= floor


def test_sufficient_existing_payoff_is_not_amplified() -> None:
    item = LayoutItem(asset_id="existing-result", x=0.5, y=0.5, width=0.3, height=0.25)
    dx, dy, scale = MotionPlanner._enforce_event_readability(
        phase=_payoff(), item=item, dx=0.02, dy=0.0, scale=1.05,
        duration=0.42, readability_duration=0.201)
    assert dx == pytest.approx(0.02, abs=1e-7)
    assert dy == 0.0
    assert scale <= 1.095
