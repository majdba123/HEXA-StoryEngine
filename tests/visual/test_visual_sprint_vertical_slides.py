"""Visual sprint Stage 4 - an asset near no side edge but near the top or bottom slides in
vertically from that edge, over the same physical reach, distance and speed as a side-edge
slide; side-edge assets keep their horizontal slide, and every slide keeps its safety checks."""
from __future__ import annotations

import pytest

from app.models import LayoutItem, MotionSegment
from app.motion.arrivals import SLIDE_DISTANCE, SLIDE_EDGE_REACH, SLIDE_MEAN_SPEED
from app.motion.timing import REFERENCE_SLIDE
from app.render.verification import EncodedMotionVerifier
from app.targets.context import active_target
from tests.visual.test_vnext2_arrivals import EDGE, _cue, _run

BOTTOM = LayoutItem(asset_id="low", x=0.5, y=0.82, width=0.2, height=0.3)    # bottom gap 0.03 h
TOP = LayoutItem(asset_id="high", x=0.5, y=0.17, width=0.2, height=0.3)      # top gap 0.02 h


@pytest.mark.parametrize("item,sign", [(BOTTOM, 1.0), (TOP, -1.0)])
def test_an_asset_near_the_top_or_bottom_slides_in_vertically_from_that_edge(item: LayoutItem, sign: float) -> None:
    planner, out = _run([_cue(item.asset_id, 1.0, 1.3)], [item])
    decision = planner.decisions[0]
    assert (decision.gesture, decision.reason) == ("SLIDE", "edge_slide_vertical")
    cue = out[item.asset_id]
    assert (cue.start, cue.end) == (1.0, 1.3)                                   # Story instants unchanged
    frames = cue.params["program"]["keyframes"]
    assert frames[0]["dx"] == 0.0 and frames[-1]["dy"] == 0.0
    aspect = active_target().width / active_target().height
    seconds = cue.params["reference_slide"]["seconds"]
    # Vertical travel is budgeted in normalized Y (encoded QA's unit), so the speed ceiling,
    # not the side-slide pixel distance, bounds it (2026-10-19: side slides grew to 0.12 w).
    distance = min(SLIDE_DISTANCE, SLIDE_MEAN_SPEED * seconds / aspect)  # mean speed, normalized Y
    assert frames[0]["dy"] == pytest.approx(sign * distance * aspect, abs=1e-6)
    segment = MotionSegment(phase="ENTRY", start=cue.start, end=cue.end, program=cue.params["program"])
    speed = EncodedMotionVerifier._max_normalized_keyframe_speed(segment, duration=cue.end - cue.start,
                                                                item_width=item.width, item_height=item.height)
    assert speed <= REFERENCE_SLIDE.max_normalized_speed


def test_a_side_edge_asset_keeps_its_horizontal_slide_even_near_the_top() -> None:
    corner = LayoutItem(asset_id="corner", x=0.12, y=0.17, width=0.18, height=0.3)
    planner, out = _run([_cue("corner", 1.0, 1.3)], [corner])
    assert (planner.decisions[0].gesture, planner.decisions[0].reason) == ("SLIDE", "edge_slide")
    assert out["corner"].params["program"]["keyframes"][0]["dy"] == 0.0


def test_vertical_reach_is_the_side_reach_in_pixels() -> None:
    aspect = active_target().width / active_target().height
    inside = SLIDE_EDGE_REACH * aspect * 0.95
    outside = SLIDE_EDGE_REACH * aspect * 1.05
    near = LayoutItem(asset_id="near", x=0.5, y=1.0 - inside - 0.15, width=0.2, height=0.3)
    far = LayoutItem(asset_id="far", x=0.5, y=1.0 - outside - 0.15, width=0.2, height=0.3)
    planner, _ = _run([_cue("near", 1.0, 1.3), _cue("far", 1.6, 1.9)], [near, far])
    gestures = {d.asset_id: d.reason for d in planner.decisions}
    assert gestures["near"] == "edge_slide_vertical" and gestures["far"] == "reference_pop"


def test_a_vertical_slide_that_would_cross_a_visible_asset_pops_instead() -> None:
    blocker = LayoutItem(asset_id="blocker", x=0.5, y=0.985, width=0.3, height=0.02)
    planner, _ = _run([_cue("blocker", 0.2, 0.5), _cue("low", 1.0, 1.3)], [blocker, BOTTOM])
    assert {d.asset_id: d.gesture for d in planner.decisions}["low"] == "POP"


def test_a_vertical_slide_never_crosses_a_hero_travel_path_in_flight() -> None:
    from app.motion.collision import box
    path = box(BOTTOM, (0.0, 0.0, 1.0))
    planner, _ = _run([_cue("low", 1.0, 1.3)], [BOTTOM], sweeps={("b", "hero"): (0.9, 1.4, path)})
    assert planner.decisions[0].gesture == "POP"


def test_side_edge_slides_are_unchanged() -> None:
    planner, out = _run([_cue("edge", 1.0, 1.3)], [EDGE])
    assert (planner.decisions[0].gesture, planner.decisions[0].reason) == ("SLIDE", "edge_slide")
    frames = out["edge"].params["program"]["keyframes"]
    assert frames[0]["dy"] == 0.0 and frames[0]["dx"] < 0
    assert "dy" not in out["edge"].params["reference_slide"]
