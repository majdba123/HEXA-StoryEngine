"""S02: four-way focus entries, real planned exits, and blur hierarchy.

These tests exercise the existing production owners rather than a second transition renderer.
"""
from __future__ import annotations

import pytest
import shutil

from app.boundary import SceneBoundaryPlanner
from app.models import CompositionBeat, LayoutItem, MotionCue, StoryBeat, VisualAsset
from app.motion.arrivals import SecondaryArrivalPlanner
from app.motion.motion_blur import MOTION_BLUR_SHUTTER, MotionBlurPolicy
from app.motion.visual_flow.direction import focus_handoff_direction
from tests.visual.test_sprint_4_5_scene_handoffs import NEW_ON_OLD, OLD_LEFT, Scene, _encode, _darkness
from app.targets import REELS_9_16
from app.targets.projection import ReferencePlanProjector
from tests.test2.render.test_motion_blur import _cue, _slide


@pytest.mark.parametrize("old,expected", [
    ((0.20, 0.50), (-1.0, 0.0)),
    ((0.80, 0.50), (1.0, 0.0)),
    ((0.50, 0.15), (0.0, -1.0)),
    ((0.50, 0.85), (0.0, 1.0)),
])
def test_first_primary_uses_all_four_focus_directions(old, expected) -> None:
    before = StoryBeat(id="b1", scene_id="s1", start=0, end=2,
                       narration="first", action="REVEAL", primary_asset_ids=["old"])
    after = StoryBeat(id="b2", scene_id="s2", start=2, end=4,
                      narration="next", action="REVEAL", primary_asset_ids=["new"])
    compositions = [
        CompositionBeat(beat_id="b1", items=[
            LayoutItem(asset_id="old", x=old[0], y=old[1], width=0.12, height=0.15)]),
        CompositionBeat(beat_id="b2", items=[
            LayoutItem(asset_id="new", x=0.5, y=0.5, width=0.12, height=0.15)]),
    ]
    layouts = {row.beat_id: row for row in compositions}
    assert focus_handoff_direction(before, after, layouts) == expected
    motion = [MotionCue(beat_id="b2", asset_id="new", kind="program_v3",
                        start=2.2, end=2.6, params={"engine_version": 3,
                        "semantic_continuity": {"mode": "ENTER"},
                        "program": {"name": "idle", "keyframes": []}})]
    assets = [VisualAsset(id="new", scene_id="s2", role="primary",
                          image_path=__import__("pathlib").Path("missing.png"),
                          extraction_method="test")]
    planner = SecondaryArrivalPlanner()
    out = planner.plan(story=[before, after], composition=compositions,
                       motion=motion, assets=assets)
    row = out[0]
    assert row.params["reference_slide"]["scene_flow"] is True
    assert planner.decisions[0].gesture == "SLIDE"
    program = next((segment.program for segment in row.segments if segment.phase == "ENTRY"),
                   row.params["program"])
    first = program["keyframes"][0]
    assert first["dx"] * expected[0] > 0 if expected[0] else first["dy"] * expected[1] > 0
    assert program["keyframes"][-1]["dx"] == 0.0
    assert program["keyframes"][-1]["dy"] == 0.0
    assert program["keyframes"][-1]["scale"] == 1.0


@pytest.mark.parametrize("position,axis,direction", [
    ((0.15, 0.72, 0.10, 0.12), 0.0, -1.0),
    ((0.85, 0.72, 0.10, 0.12), 0.0, 1.0),
    ((0.80, 0.13, 0.10, 0.10), 1.0, -1.0),
    ((0.80, 0.87, 0.10, 0.10), 1.0, 1.0),
])
def test_hero_exit_can_plan_each_cardinal_axis(position, axis, direction) -> None:
    scene = Scene(lead=16, later=None, opener=NEW_ON_OLD,
                  old={"old_a": OLD_LEFT, "old_b": position})
    scene.story[0] = scene.story[0].model_copy(update={
        "active_visual_semantic_state": {"old_a": "old_a", "old_b": "old_b"}})
    scene.motion = [
        cue.model_copy(update={"params": {**cue.params, "scene_hero": True}})
        if (cue.beat_id, cue.asset_id) == ("b1", "old_b") else cue
        for cue in scene.motion
    ]
    result = scene.plan(SceneBoundaryPlanner())
    assert result.audit["hero_exit"] == "full_frame_exit", result.audit
    spec = result.overlap_exits["old_b"]
    assert spec["axis"] == axis
    assert spec["direction"] == direction
    assert spec["end"] > spec["start"]
    assert result.audit["opener_frame"] == 16


def test_motion_blur_prioritizes_largest_moving_icon_and_preserves_other() -> None:
    motion = [
        _cue(_slide(0.3)),
        _cue(_slide(0.3)).model_copy(update={"asset_id": "B"}),
    ]
    layout = [CompositionBeat(beat_id="b", items=[
        LayoutItem(asset_id="A", x=0.2, y=0.5, width=0.1, height=0.15),
        LayoutItem(asset_id="B", x=0.7, y=0.5, width=0.25, height=0.35),
    ])]
    out = MotionBlurPolicy().plan(motion, layout, width=1920, height=1080, fps=30)
    assert out[0].params["motion_blur"]["shutter"] == MOTION_BLUR_SHUTTER
    assert out[1].params["motion_blur"]["visual_mass_lead"] is True
    assert out[1].params["motion_blur"]["shutter"] > MOTION_BLUR_SHUTTER


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg required")
def test_vertical_exit_clears_youtube_in_encoded_frames(tmp_path) -> None:
    """A top/bottom choice is actually rendered vertically, not only logged."""
    position = (0.8, 0.87, 0.1, 0.1)
    scene = Scene(lead=16, later=None, opener=NEW_ON_OLD, root=tmp_path,
                  old={"old_a": OLD_LEFT, "old_b": position})
    scene.story[0] = scene.story[0].model_copy(update={
        "active_visual_semantic_state": {"old_a": "old_a", "old_b": "old_b"}})
    scene.motion = [
        cue.model_copy(update={"params": {**cue.params, "scene_hero": True}})
        if (cue.beat_id, cue.asset_id) == ("b1", "old_b") else cue
        for cue in scene.motion
    ]
    row = scene.plan(SceneBoundaryPlanner())
    spec = row.overlap_exits["old_b"]
    assert spec["axis"] == 1.0 and spec["direction"] == 1.0
    frames = _encode(scene, [row], tmp_path / "vertical")
    start = scene.frame(spec["start"])
    end = scene.frame(spec["end"])
    # In the 2nd segment, the old icon stays until the opener, travels, and disappears.
    assert _darkness(frames, position, pad=0.01)[60 + start] > 0.8
    assert _darkness(frames, position, pad=0.01)[60 + end + 1] < 0.03


def test_vertical_exit_includes_reels_letterbox_padding() -> None:
    """A vertical exit must pass the actual 9:16 viewport, not the 16:9 content."""
    padding = ReferencePlanProjector.reference_padding(REELS_9_16)[1]
    assert padding > 0
    # The default fixture's RIGHT exit is unrelated to this test: verify only
    # that the layout-safe planning margin includes the vertical projection pad.
    planner = SceneBoundaryPlanner(vertical_padding=padding)
    assert planner.vertical_exit_margin >= padding
    assert planner.exit_margin < planner.vertical_exit_margin
