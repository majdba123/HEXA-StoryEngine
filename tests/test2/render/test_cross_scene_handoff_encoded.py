"""Roadmap V2 Sprint 7 - renderer execution of a planned cross-scene handoff (encoded frames).

The renderer only executes ``handoff_from`` (runtime asset ids): the outgoing artwork stays
still and opaque through the frame before its successor's first visible frame, and the
successor appears on exactly that frame at the inherited pose. No gap, no duplicate.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

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
from app.motion.cross_scene import CONTINUITY_PROGRAM, HANDOFF_PARAM
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
    return np.frombuffer(raw, np.uint8).reshape(-1, height, width, 3).astype(int)


def _mask(frames: np.ndarray, colour) -> np.ndarray:
    return (np.abs(frames - np.array(colour)).sum(axis=3) < 90)


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
