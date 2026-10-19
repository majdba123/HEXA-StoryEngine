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


def _relation_cue(asset: str, phase: str, *, source: str, target: str, start: float = 1.0, seconds: float = 0.4):
    from app.models import MotionSegment
    from tests.visual.test_vnext2_arrivals import _cue

    nudge = {"name": "reference_focus_handoff", "settle_progress": 0.6, "semantic_peak_progress": 0.37,
             "keyframes": [{"progress": 0.0, "dx": 0.0, "dy": 0.0, "scale": 1.0},
                           {"progress": 0.37, "dx": 0.011, "dy": 0.0, "scale": 1.02},
                           {"progress": 0.6, "dx": 0.0, "dy": 0.0, "scale": 1.0},
                           {"progress": 1.0, "dx": 0.0, "dy": 0.0, "scale": 1.0}]}
    row = MotionSegment(phase=phase, start=start, end=start + seconds, program=nudge, source_asset_id=source,
                        target_asset_id=target, relationship="ENABLES")
    return _cue(asset, start, start + seconds, segments=[row])


@pytest.mark.parametrize("phase,asset,partner_x,expected_sign", [
    ("INTERACT", "source", 0.80, -1.0),   # the source approaches a target on its right: enters from the LEFT
    ("REACT", "target", 0.20, -1.0),      # the target moves away from a source on its left: enters from the LEFT
])
def test_a_relation_accent_at_the_reveal_becomes_one_travel_along_the_relation(
        phase: str, asset: str, partner_x: float, expected_sign: float) -> None:
    from app.models import CompositionBeat
    from app.motion.arrivals import SecondaryArrivalPlanner
    from tests.visual.test_vnext2_arrivals import _assets

    partner = "target" if asset == "source" else "source"
    item = LayoutItem(asset_id=asset, x=0.5, y=0.45, width=0.16, height=0.22)
    other = LayoutItem(asset_id=partner, x=partner_x, y=0.45, width=0.12, height=0.18)
    cue = _relation_cue(asset, phase, source="source", target="target")
    planner = SecondaryArrivalPlanner()
    out = planner.plan(story=[_beat("b", 0.0, 3.0), _beat("n", 3.0, 5.0)],
                       composition=[CompositionBeat(beat_id="b", items=[item, other])],
                       motion=[cue], assets=_assets(asset, partner))
    moved = next(row for row in out if row.asset_id == asset)
    segment = moved.segments[0]
    first = segment.program["keyframes"][0]
    assert segment.phase == phase and (segment.start, segment.end) == (1.0, 1.4)   # same event, same window
    assert first["dx"] * expected_sign > 0.02 and first["scale"] < 1.0                # one travel, growing
    assert all(f["dx"] * expected_sign >= -1e-9 for f in segment.program["keyframes"]), "no out-and-back"
    assert segment_contract_violations(phase=phase, program=segment.program, params=moved.params,
                                       segment_duration=0.4, item_width=item.width, item_height=item.height) == []


def _beat(beat_id: str, start: float, end: float):
    from app.models import StoryBeat

    return StoryBeat(id=beat_id, scene_id=f"s-{beat_id}", start=start, end=end, narration="x", action="REVEAL")
