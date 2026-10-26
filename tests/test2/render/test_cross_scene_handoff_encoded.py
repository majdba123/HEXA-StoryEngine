"""Roadmap V2 Sprint 7 - renderer execution of a planned cross-scene handoff (encoded frames).

The renderer only executes ``handoff_from`` (runtime asset ids): the outgoing artwork stays
still and opaque through the frame before its successor's first visible frame, and the
successor appears on exactly that frame at the inherited pose. No gap, no duplicate.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image, ImageDraw

from app.models import (
    AssetActivation,
    CompositionBeat,
    LayoutItem,
    MotionCue,
    MotionSegment,
    RenderPlan,
    StoryBeat,
    VisualAsset,
)
from app.motion.cross_scene import CONTINUITY_PROGRAM, HANDOFF_PARAM, NARRATIVE_FOCUS, CrossSceneContinuityPlanner
from app.render.renderer import FFmpegRenderer
from app.shared.errors import StageFailedError
from app.targets import REELS_9_16
from app.targets.projection import ReferencePlanProjector

FPS = 30
RED, BLUE, GREEN = (220, 30, 30), (30, 60, 220), (30, 160, 60)


def _png(path: Path, colour) -> Path:
    Image.new("RGBA", (200, 300), (*colour, 255)).save(path)
    return path


def _plan(tmp_path: Path, *, handoff: bool = True, dx: float = -0.05, reveal: float = 1.3) -> RenderPlan:
    old = _png(tmp_path / "old.png", RED)
    new = _png(tmp_path / "new.png", BLUE)
    other = _png(tmp_path / "other.png", GREEN)
    assets = [
        VisualAsset(id="S1:a", scene_id="S1", role="primary", image_path=old, extraction_method="test"),
        VisualAsset(id="S2:a", scene_id="S2", role="primary", image_path=new, extraction_method="test"),
        VisualAsset(id="S2:b", scene_id="S2", role="supporting", image_path=other, extraction_method="test"),
    ]
    story = [
        StoryBeat(id="b1", scene_id="S1", start=0.0, end=1.0, narration="a", action="REVEAL", primary_asset_ids=["S1:a"],
                  asset_activations=[AssetActivation(asset_id="S1:a", semantic_unit_id="P1")]),
        StoryBeat(id="b2", scene_id="S2", start=1.0, end=2.0, narration="b", action="REVEAL", primary_asset_ids=["S2:a"],
                  support_asset_ids=["S2:b"], asset_activations=[AssetActivation(asset_id="S2:a", semantic_unit_id="P2"),
                                     AssetActivation(asset_id="S2:b", semantic_unit_id="P3")]),
    ]
    composition = [
        CompositionBeat(beat_id="b1", items=[LayoutItem(asset_id="S1:a", x=0.30, y=0.5, width=0.10, height=0.30)]),
        CompositionBeat(beat_id="b2", items=[LayoutItem(asset_id="S2:a", x=0.30 - dx, y=0.5, width=0.08, height=0.30),
                                             LayoutItem(asset_id="S2:b", x=0.80, y=0.5, width=0.10, height=0.30, z=1)]),
    ]
    params = {"engine_version": 3}
    entry = MotionSegment(phase="ENTRY", start=reveal, end=reveal + 0.3,
                          program={"name": "pop", "keyframes": [{"progress": 0.0, "dx": 0, "dy": 0, "scale": 1.0},
                                                                {"progress": 1.0, "dx": 0, "dy": 0, "scale": 1.0}]})
    if handoff:
        params[HANDOFF_PARAM] = {"beat_id": "b1", "asset_id": "S1:a"}
        entry = MotionSegment(phase="ENTRY", start=reveal, end=reveal + 0.5, semantic_action="CONTINUE",
                              program={"name": CONTINUITY_PROGRAM, "keyframes": [
                                  {"progress": 0.0, "dx": dx, "dy": 0.0, "scale": 1.0, "easing": "ease_in_out_cubic"},
                                  {"progress": 1.0, "dx": 0.0, "dy": 0.0, "scale": 1.0, "easing": "ease_out_cubic"}]})
    motion = [
        MotionCue(beat_id="b1", asset_id="S1:a", kind="program_v3", start=0.2, end=0.4, params={"engine_version": 3},
                  segments=[MotionSegment(phase="ENTRY", start=0.2, end=0.4, program={"name": "pop", "keyframes": [
                      {"progress": 0.0, "dx": 0, "dy": 0, "scale": 1.0}, {"progress": 1.0, "dx": 0, "dy": 0, "scale": 1.0}]})]),
        MotionCue(beat_id="b2", asset_id="S2:a", kind="program_v3", start=reveal, end=entry.end, params=params, segments=[entry]),
        MotionCue(beat_id="b2", asset_id="S2:b", kind="program_v3", start=1.1, end=1.4, params={"engine_version": 3},
                  segments=[MotionSegment(phase="ENTRY", start=1.1, end=1.4, program={"name": "pop", "keyframes": [
                      {"progress": 0.0, "dx": 0, "dy": 0, "scale": 1.0}, {"progress": 1.0, "dx": 0, "dy": 0, "scale": 1.0}]})]),
    ]
    return RenderPlan(duration=2.0, story=story, composition=composition, motion=motion, assets=assets)


def _frames(video: Path, width: int, height: int) -> np.ndarray:
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(video), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, height, width, 3)


def _mask(frames: np.ndarray, colour) -> np.ndarray:
    # The exact RGB distance fits in int16 (maximum 765). Process one frame at a
    # time so this 1080p encoded assertion does not allocate multi-GiB int64 arrays.
    mask = np.empty(frames.shape[:-1], dtype=bool)
    for index, frame in enumerate(frames):
        distance = np.zeros(frame.shape[:2], dtype=np.int16)
        for channel, value in enumerate(colour):
            distance += np.abs(frame[:, :, channel].astype(np.int16) - int(value))
        mask[index] = distance < 90
    return mask


def _centre_x(mask: np.ndarray) -> float | None:
    xs = np.nonzero(mask)[1]
    return float(xs.mean()) if xs.size else None


@pytest.mark.parametrize("target", ["youtube", "reels"])
def test_handoff_swaps_on_one_frame_without_gap_duplicate_or_jump(tmp_path: Path, target: str) -> None:
    plan = _plan(tmp_path)
    if target == "reels":
        plan = ReferencePlanProjector().project(plan, REELS_9_16, tmp_path / "reels")
        assert plan.motion[1].params[HANDOFF_PARAM] == {"beat_id": "b1", "asset_id": "S1:a"}
    video = FFmpegRenderer().render(plan, tmp_path / f"{target}.mp4")
    frames = _frames(video, plan.width, plan.height)
    red, blue = _mask(frames, RED), _mask(frames, BLUE)
    swap = 39  # first frame at/after the unchanged reveal 1.3 s
    # The narrower successor cannot hide its predecessor: any overlap frame shows red edges.
    reference_red = red[30].sum()
    for index in range(12, swap):  # predecessor never drifts, fades or doubles before the swap
        assert abs(int(red[index].sum()) - int(reference_red)) <= 0.03 * reference_red, index
    for index in range(12, len(frames)):  # from old reveal to the end
        has_red, has_blue = red[index].sum() > 500, blue[index].sum() > 500
        assert has_red != has_blue, f"frame {index}: red={has_red} blue={has_blue} (gap or duplicate)"
        assert has_red == (index < swap)
    # Perceived pose continues across the swap, then settles on Composition.
    before, at = _centre_x(red[swap - 1]), _centre_x(blue[swap])
    assert abs(before - at) <= 0.004 * plan.width
    settled = _centre_x(blue[-1])
    assert abs(settled - before) > 0.03 * plan.width


def test_without_handoff_the_certified_bridge_still_runs(tmp_path: Path) -> None:
    plan = _plan(tmp_path, handoff=False)
    frames = _frames(FFmpegRenderer().render(plan, tmp_path / "legacy.mp4"), plan.width, plan.height)
    red, blue = _mask(frames, RED), _mask(frames, BLUE)
    # Certified MOTION_HANDOFF: the old artwork leaves around the first incoming reveal
    # (1.1 s), well before its successor appears at 1.3 s: there is a referent gap.
    gap = [i for i in range(31, 39) if red[i].sum() < 500 and blue[i].sum() < 500]
    assert gap


@pytest.mark.parametrize("size", [(320, 180), (180, 320)])
def test_v2_authored_artwork_swap_has_one_opaque_carrier_per_frame(tmp_path: Path, size) -> None:
    baseline = _plan(tmp_path, handoff=False, dx=0.0)
    baseline.composition[1].items[0].width = 0.10
    baseline.story[0].asset_activations[0].continuity = {
        "mode": "TRANSFORM_TO", "target_asset_id": "P2"}
    baseline.story[1].asset_activations[0].spoken_start = 1.3
    cue = baseline.motion[1]
    baseline.motion[1] = cue.model_copy(update={"segments": [], "params": {
        **cue.params, "program": {"name": "fresh_slide", "keyframes": [
            {"progress": 0.0, "dx": 0.2, "dy": 0.0, "scale": 0.8},
            {"progress": 1.0, "dx": 0.0, "dy": 0.0, "scale": 1.0},
        ]}}})
    baseline = baseline.model_copy(update={"width": size[0], "height": size[1]})
    package = SimpleNamespace(scenes=[SimpleNamespace(id="S1", order=0, units=[]),
                                      SimpleNamespace(id="S2", order=1, units=[])])
    planner = CrossSceneContinuityPlanner()
    motion = planner.plan(
        package=package, story=baseline.story, composition=baseline.composition,
        motion=baseline.motion, assets=baseline.assets, duration=baseline.duration,
        frame_width=size[0], frame_height=size[1], enable_visual_continuity_v2=True)
    assert len(planner.decisions) == 1 and planner.decisions[0].accepted
    assert planner.decisions[0].identity_authority == "AUTHORED_CONTINUITY"
    assert next(row for row in motion if row.asset_id == "S2:a").params["program"]["name"] == CONTINUITY_PROGRAM
    candidate = baseline.model_copy(update={"motion": motion})
    frames = _frames(FFmpegRenderer().render(candidate, tmp_path / "v2.mp4"), *size)
    red, blue = _mask(frames, RED), _mask(frames, BLUE)
    for index in range(12, len(frames)):
        assert (red[index].sum() > 50) != (blue[index].sum() > 50), index
        assert (red[index].sum() > 50) == (index < 39), index
    assert abs(_centre_x(red[38]) - _centre_x(blue[39])) <= 0.01 * size[0]


def test_v2_two_authored_character_poses_swap_independently(tmp_path: Path) -> None:
    plan = _plan(tmp_path, handoff=False, dx=0.0)
    plan.width, plan.height = 320, 180

    def pose(name: str, colour: tuple[int, int, int], *, raised: bool) -> Path:
        path = tmp_path / name
        image = Image.new("RGBA", (200, 300), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        paint = (*colour, 255)
        draw.ellipse((70, 18, 130, 78), fill=paint)
        draw.rectangle((65, 78, 135, 225), fill=paint)
        draw.line((70, 100, 30, 45 if raised else 190), fill=paint, width=18)
        draw.line((130, 100, 170, 45 if raised else 190), fill=paint, width=18)
        draw.line((84, 215, 74, 285), fill=paint, width=18)
        draw.line((116, 215, 126, 285), fill=paint, width=18)
        image.save(path)
        return path

    plan.assets[0].image_path = pose("first-standing.png", RED, raised=False)
    plan.assets[1].image_path = pose("first-pointing.png", BLUE, raised=True)
    plan.story[0].asset_activations[0].continuity = {
        "mode": "TRANSFORM_TO", "target_asset_id": "P2"}
    plan.story[1].asset_activations[0].spoken_start = 1.3
    plan.story[1].support_asset_ids = []
    plan.story[1].asset_activations = plan.story[1].asset_activations[:1]
    plan.composition[1].items = plan.composition[1].items[:1]
    plan.motion = plan.motion[:2]
    old_second = pose("second-pointing.png", GREEN, raised=True)
    new_second = pose("second-standing.png", (220, 170, 30), raised=False)
    plan.assets.extend([
        VisualAsset(id="S1:c", scene_id="S1", role="supporting", image_path=old_second,
                    extraction_method="test"),
        VisualAsset(id="S2:c", scene_id="S2", role="supporting", image_path=new_second,
                    extraction_method="test"),
    ])
    plan.story[0].support_asset_ids.append("S1:c")
    plan.story[0].asset_activations.append(AssetActivation(
        asset_id="S1:c", semantic_unit_id="P3",
        continuity={"mode": "TRANSFORM_TO", "target_asset_id": "P4"}))
    plan.story[1].support_asset_ids.append("S2:c")
    plan.story[1].asset_activations.append(AssetActivation(
        asset_id="S2:c", semantic_unit_id="P4", spoken_start=1.5))
    plan.composition[0].items.append(LayoutItem(asset_id="S1:c", x=0.70, y=0.5, width=0.10, height=0.30))
    plan.composition[1].items.append(LayoutItem(asset_id="S2:c", x=0.70, y=0.5, width=0.10, height=0.30))
    plan.motion.append(plan.motion[0].model_copy(update={"asset_id": "S1:c"}))
    plan.motion.append(plan.motion[1].model_copy(update={"asset_id": "S2:c", "start": 1.5,
                                                 "end": 1.8, "segments": []}))
    package = SimpleNamespace(scenes=[SimpleNamespace(id="S1", order=0, units=[]),
                                      SimpleNamespace(id="S2", order=1, units=[])])
    planner = CrossSceneContinuityPlanner()
    motion = planner.plan(package=package, story=plan.story, composition=plan.composition,
                          motion=plan.motion, assets=plan.assets, duration=plan.duration,
                          frame_width=plan.width, frame_height=plan.height,
                          enable_visual_continuity_v2=True)
    assert len(planner.decisions) == 2 and all(row.accepted for row in planner.decisions)
    assert {cue.params[HANDOFF_PARAM]["asset_id"] for cue in motion if HANDOFF_PARAM in cue.params} == {
        "S1:a", "S1:c"}
    frames = _frames(FFmpegRenderer().render(plan.model_copy(update={"motion": motion}),
                                            tmp_path / "two-poses.mp4"), plan.width, plan.height)
    for old_colour, new_colour, x0, x1, swap in ((RED, BLUE, 0, 160, 39),
                                                  (GREEN, (220, 170, 30), 160, 320, 45)):
        old = _mask(frames[:, :, x0:x1], old_colour)
        new = _mask(frames[:, :, x0:x1], new_colour)
        for index in range(12, len(frames)):
            assert (old[index].sum() > 50) != (new[index].sum() > 50), index
            assert (old[index].sum() > 50) == (index < swap), index


def test_v2_renderer_rejects_a_future_pose_before_spoken_authority(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    plan.width, plan.height = 320, 180
    plan.motion[1].params["visual_continuity_v2"] = True
    plan.story[1].asset_activations[0].spoken_start = 1.5
    with pytest.raises(StageFailedError) as exc_info:
        FFmpegRenderer().render(plan, tmp_path / "premature-pose.mp4")
    assert exc_info.value.effective_code == "HANDOFF_REVEAL_EARLY"


@pytest.mark.parametrize("size", [(320, 180), (180, 320)])
def test_focus_continuity_changes_encoded_entry_without_claiming_identity(tmp_path: Path, size) -> None:
    baseline = _plan(tmp_path, handoff=False, dx=-0.25)
    baseline = baseline.model_copy(update={"width": size[0], "height": size[1]})
    package = SimpleNamespace(scenes=[SimpleNamespace(id="S1", order=0, units=[]),
                                      SimpleNamespace(id="S2", order=1, units=[])])
    planner = CrossSceneContinuityPlanner()
    candidate_motion = planner.plan(
        package=package, story=baseline.story, composition=baseline.composition,
        motion=baseline.motion, assets=baseline.assets, duration=baseline.duration,
        frame_width=size[0], frame_height=size[1], enable_focus_continuity=True,
    )
    assert len(planner.decisions) == 1
    assert planner.decisions[0].decision == NARRATIVE_FOCUS
    assert planner.decisions[0].identity_authority == "NONE"
    candidate = baseline.model_copy(update={"motion": candidate_motion})
    old_frames = _frames(FFmpegRenderer().render(baseline, tmp_path / "baseline.mp4"), *size)
    new_frames = _frames(FFmpegRenderer().render(candidate, tmp_path / "candidate.mp4"), *size)
    old_blue, new_blue = _mask(old_frames, BLUE), _mask(new_frames, BLUE)
    # Same input and reveal frame; the attention lead is visible and settles on
    # exactly the original Composition position.
    assert old_blue[38].sum() == new_blue[38].sum() == 0
    assert abs(_centre_x(old_blue[39]) - _centre_x(new_blue[39])) >= 0.015 * size[0]
    assert abs(_centre_x(old_blue[-1]) - _centre_x(new_blue[-1])) <= 1.0


@pytest.mark.parametrize("spec", [
    {"beat_id": "b0", "asset_id": "S1:a"},
    {"beat_id": "b1", "asset_id": "S1:missing"},
    "S1:a",
])
def test_invalid_handoff_instruction_fails_closed(tmp_path: Path, spec) -> None:
    plan = _plan(tmp_path)
    plan.motion[1].params[HANDOFF_PARAM] = spec
    with pytest.raises(StageFailedError) as caught:
        FFmpegRenderer().render(plan, tmp_path / "bad.mp4")
    assert caught.value.details["code"] == "HANDOFF_SOURCE_INVALID"
