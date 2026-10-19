"""Motion language corrections from the encoded review of export v4 (2026-10-19)."""
from __future__ import annotations

from math import hypot

import pytest

from app.choreography import EventFlowStage
from app.models import LayoutItem
from app.motion.contract import segment_contract_violations
from app.motion.event_flow import MotionEventPhase
from app.motion.planner import MotionPlanner
from app.motion.visual_flow.direction import spatial_entry_direction


def test_near_corner_art_enters_laterally_unless_a_vertical_edge_is_clearly_closer() -> None:
    # Black Hat opening shield: right gap 130 px, bottom gap 112 px -> RIGHT, not BOTTOM.
    shield = LayoutItem(asset_id="shield", x=0.824, y=0.678, width=0.216, height=0.436)
    assert spatial_entry_direction(shield, frame_width=1920, frame_height=1080) == (1.0, 0.0)
    # A tall centred character whose box nearly touches the bottom still rises.
    character = LayoutItem(asset_id="character", x=0.496, y=0.512, width=0.35, height=0.915)
    assert spatial_entry_direction(character, frame_width=1920, frame_height=1080) == (0.0, 1.0)


def _result(*, relationship: str | None = None, target: str | None = None) -> MotionEventPhase:
    return MotionEventPhase(
        event_id="e", event_order=0, stage=EventFlowStage.PAYOFF, step_index=0, involvement="RESULT",
        focus_asset_id="r", source_asset_id=None, target_asset_id=target, result_asset_id="r",
        relationship=relationship, semantic_action="REVEAL", authority="EXPLICIT")


@pytest.mark.parametrize("vector", [(1.0, 0.0), (-1.0, 0.2), (0.6, 0.4)])
def test_a_resolved_result_rises_instead_of_shaking_sideways(vector) -> None:
    item = LayoutItem(asset_id="r", x=0.5, y=0.6, width=0.16, height=0.2)
    program = MotionPlanner._event_segment_program(
        phase=_result(), vector=vector, item=item, focus_strength=1.0, energy=1.0, cohort_gain=1.0,
        duration=0.42)
    frames = [{"progress": f.progress, "dx": f.dx, "dy": f.dy, "scale": f.scale} for f in program.keyframes]
    assert all(abs(f["dx"]) < 1e-12 for f in frames), "no lateral PAYOFF nudge"
    assert min(f["dy"] for f in frames) < 0.0, "the accent lifts the result"
    assert segment_contract_violations(phase="PAYOFF", program={"keyframes": frames, "name": program.name},
                                       params={}, segment_duration=0.42, item_width=item.width,
                                       item_height=item.height) == []


def test_a_relational_payoff_keeps_its_authored_direction() -> None:
    item = LayoutItem(asset_id="r", x=0.5, y=0.6, width=0.16, height=0.2)
    program = MotionPlanner._event_segment_program(
        phase=_result(relationship="CAUSES", target="t"), vector=(1.0, 0.0), item=item, focus_strength=1.0,
        energy=1.0, cohort_gain=1.0, duration=0.42)
    assert max(abs(f.dx) for f in program.keyframes) > 0.0
    assert max(hypot(f.dx, f.dy) for f in program.keyframes) > 0.0
