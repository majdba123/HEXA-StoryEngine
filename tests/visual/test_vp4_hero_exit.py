"""VP4: the outgoing scene's hero leaves the canvas completely inside the next segment.

Boundary plans it (only the hero Motion marked, only on a crisp change, never a continuing
referent, a clean cut when incoming artwork or text is on the path); the renderer executes
the plan: still until the unchanged opener, then a smoothstep slide fully off the canvas.
"""
from __future__ import annotations

import shutil

import pytest

from app.boundary import SceneBoundaryPlanner
from app.motion.hero_travel import HERO_TRAVEL, SMOOTHSTEP_PEAK
from tests.visual.test_sprint_4_5_scene_handoffs import NEW_ON_OLD, OLD_RIGHT, Scene, _darkness, _encode, _region


# -- full-frame exit -----------------------------------------------------------------------------
def _exit_scene(hero: str, *, opener=NEW_ON_OLD, lead: int = 16, root=None) -> Scene:
    """CRISP_HANDOFF fixture (as VP2-A): the opener lands on old_a's spot; old_b is free."""
    scene = Scene(lead=lead, opener=opener, later=None, root=root)
    scene.story[0] = scene.story[0].model_copy(update={
        "active_visual_semantic_state": {"old_a": "old_a", "old_b": "old_b"}})
    scene.motion = [c.model_copy(update={"params": {**c.params, "scene_hero": True}})
                    if (c.beat_id, c.asset_id) == ("b1", hero) else c for c in scene.motion]
    return scene


def test_boundary_plans_a_full_frame_exit_for_the_marked_hero_only() -> None:
    scene = _exit_scene("old_b")                                         # OLD_RIGHT: leaves right
    row = scene.plan(SceneBoundaryPlanner(horizontal_padding=0.0952))
    assert row.audit["hero_exit"] == "full_frame_exit"
    assert set(row.overlap_exits) == {"old_b"} and "old_b" not in row.exit_starts
    spec = row.overlap_exits["old_b"]
    assert spec["direction"] == 1.0
    assert scene.frame(spec["start"]) == row.audit["opener_frame"] == 16    # opener unchanged
    assert row.mode in {"HARD_CUT", "CRISP_HANDOFF", "HOLD_TO_OPENER"}
    distance = 1 - (OLD_RIGHT[0] - OLD_RIGHT[2] / 2) + 0.01 + 0.0952
    assert spec["end"] - spec["start"] >= SMOOTHSTEP_PEAK * distance / HERO_TRAVEL.max_normalized_speed - 1e-9
    assert _exit_scene("nobody").plan().overlap_exits == {}


def test_incoming_artwork_on_the_path_or_a_continuing_referent_means_a_clean_cut() -> None:
    blocked = _exit_scene("old_a").plan()                                 # opener lands on the hero
    assert blocked.overlap_exits == {} and blocked.audit["hero_exit"].startswith("clean_cut:")
    scene = _exit_scene("old_b")
    scene.motion = [c.model_copy(update={"params": {**c.params, "handoff_from": {"beat_id": "b1",
                                                                                "asset_id": "old_b"}}})
                    if c.beat_id == "b2" else c for c in scene.motion]
    row = scene.plan()
    assert row.overlap_exits == {}
    assert row.audit["hero_exit"] in {"clean_cut:referent_continues"} or row.audit["hero_exit"].startswith("clean_cut")


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg required")
def test_encoded_hero_stays_until_the_opener_then_leaves_the_canvas_completely(tmp_path) -> None:
    scene = _exit_scene("old_b", root=tmp_path)
    row = scene.plan(SceneBoundaryPlanner(horizontal_padding=0.0))
    assert row.overlap_exits
    frames = _encode(scene, [row], tmp_path / "exit")
    b = 60                                                               # first frame of the new beat
    spec = row.overlap_exits["old_b"]
    start, end = scene.frame(spec["start"]), scene.frame(spec["end"])
    hero = _darkness(frames, OLD_RIGHT)
    assert hero[b] > 0.9                                                 # carried into the new scene
    assert hero[b + start] > 0.9                                         # still until the opener
    assert hero[b + end + 1] < 0.02                                      # gone from its place
    right_edge = frames[(b + end + 1, *_region((0.98, OLD_RIGHT[1], 0.04, OLD_RIGHT[3])))]
    assert right_edge.mean() > 250                                       # and off the canvas
    mid = b + (start + end) // 2
    along_path = _darkness(frames, (0.95, OLD_RIGHT[1], 0.1, OLD_RIGHT[3]), pad=0.0)
    assert along_path[mid] > 0.05 and along_path[b + start] < 0.02      # visibly travelling there


def test_exit_never_slides_past_a_held_referent_carrier() -> None:
    """Sprint 7 may hold an authored referent carrier into the next scene: it is an obstacle."""
    scene = Scene(lead=16, opener=NEW_ON_OLD, later=None,
                  old={"old_a": (0.2, 0.3, 0.2, 0.3), "old_b": (0.6, 0.3, 0.2, 0.3), "keep": (0.88, 0.3, 0.15, 0.3)})
    scene.story[0] = scene.story[0].model_copy(update={
        "active_visual_semantic_state": {"old_a": "old_a", "old_b": "old_b", "keep": "keep"}})
    scene.motion = [
        c.model_copy(update={"params": {**c.params, "scene_hero": True}}) if (c.beat_id, c.asset_id) == ("b1", "old_b")
        else c.model_copy(update={"params": {**c.params, "referent_carrier": True}})
        if (c.beat_id, c.asset_id) in {("b1", "keep"), ("b1", "old_a")} else c
        for c in scene.motion]
    row = scene.plan()
    assert row.overlap_exits == {}
    assert "path_crosses_held_outgoing_artwork" in row.audit["hero_exit"]
