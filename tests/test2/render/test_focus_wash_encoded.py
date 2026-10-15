"""Cinematic VNext2 - renderer execution of a planned backdrop wash (encoded frames).

The renderer only executes ``focus_wash`` (Motion owns the decision): before the wash
the frame is untouched; once it is on, everything except the resolved focus is blurred
and tinted toward grey on one clock, the focus stays pixel-crisp above it, and a scene
that holds the washed picture before its own opener keeps the wash (no crisp flicker).
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from app.models import AssetActivation, CompositionBeat, LayoutItem, MotionCue, MotionSegment, RenderPlan, StoryBeat, VisualAsset
from app.render.renderer import FFmpegRenderer
from app.targets import REELS_9_16
from app.targets.projection import ReferencePlanProjector

RED, BLUE, GREEN = (220, 30, 30), (30, 60, 220), (30, 160, 60)
WASH = {"start": 1.0, "end": 2.0, "ramp": 0.2, "blur_px": 9.0, "tint": "#9C9C9C", "tint_alpha": 0.42,
        "focus_asset_ids": ["S1:focus"]}


def _png(path: Path, colour) -> Path:
    Image.new("RGBA", (200, 300), (*colour, 255)).save(path)
    return path


def _still(start: float, end: float) -> MotionSegment:
    return MotionSegment(phase="ENTRY", start=start, end=end, program={"name": "pop", "keyframes": [
        {"progress": 0.0, "dx": 0, "dy": 0, "scale": 1.0}, {"progress": 1.0, "dx": 0, "dy": 0, "scale": 1.0}]})


def _plan(tmp_path: Path, *, wash: dict | None = WASH) -> RenderPlan:
    paths = {name: _png(tmp_path / f"{name}.png", colour) for name, colour in
             (("backdrop", RED), ("focus", BLUE), ("next", GREEN))}
    assets = [VisualAsset(id="S1:backdrop", scene_id="S1", role="supporting", image_path=paths["backdrop"],
                          extraction_method="test"),
              VisualAsset(id="S1:focus", scene_id="S1", role="primary", image_path=paths["focus"], extraction_method="test"),
              VisualAsset(id="S2:next", scene_id="S2", role="primary", image_path=paths["next"], extraction_method="test")]
    story = [
        StoryBeat(id="b1", scene_id="S1", start=0.0, end=2.0, narration="a", action="REVEAL",
                  primary_asset_ids=["S1:focus"], support_asset_ids=["S1:backdrop"],
                  asset_activations=[AssetActivation(asset_id="S1:backdrop", semantic_unit_id="P1"),
                                     AssetActivation(asset_id="S1:focus", semantic_unit_id="P2")]),
        StoryBeat(id="b2", scene_id="S2", start=2.0, end=3.0, narration="b", action="REVEAL",
                  primary_asset_ids=["S2:next"], asset_activations=[AssetActivation(asset_id="S2:next",
                                                                                     semantic_unit_id="P3")]),
    ]
    composition = [
        CompositionBeat(beat_id="b1", items=[LayoutItem(asset_id="S1:backdrop", x=0.25, y=0.5, width=0.12, height=0.3),
                                             LayoutItem(asset_id="S1:focus", x=0.75, y=0.5, width=0.12, height=0.3, z=1)]),
        CompositionBeat(beat_id="b2", items=[LayoutItem(asset_id="S2:next", x=0.5, y=0.5, width=0.12, height=0.3)]),
    ]
    focus_params = {"engine_version": 3}
    if wash is not None:
        focus_params["focus_wash"] = dict(wash)
    motion = [
        MotionCue(beat_id="b1", asset_id="S1:backdrop", kind="program_v3", start=0.2, end=0.4,
                  params={"engine_version": 3}, segments=[_still(0.2, 0.4)]),
        MotionCue(beat_id="b1", asset_id="S1:focus", kind="program_v3", start=1.0, end=1.2,
                  params=focus_params, segments=[_still(1.0, 1.2)]),
        MotionCue(beat_id="b2", asset_id="S2:next", kind="program_v3", start=2.1, end=2.3,
                  params={"engine_version": 3}, segments=[_still(2.1, 2.3)]),
    ]
    return RenderPlan(duration=3.0, story=story, composition=composition, motion=motion, assets=assets)


def _frames(video: Path, width: int, height: int) -> np.ndarray:
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(video), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, height, width, 3)


def _box(plan: RenderPlan, asset_id: str, beat: str = "b1", inset: float = 0.25) -> tuple[slice, slice]:
    item = next(i for b in plan.composition if b.beat_id == beat for i in b.items if i.asset_id == asset_id)
    w, h = item.width * plan.width, item.height * plan.height
    x0, y0 = item.x * plan.width - w / 2, item.y * plan.height - h / 2
    return (slice(int(y0 + h * inset), int(y0 + h * (1 - inset))), slice(int(x0 + w * inset), int(x0 + w * (1 - inset))))


@pytest.mark.parametrize("target", ["youtube", "reels"])
def test_wash_recedes_the_backdrop_and_keeps_the_focus_crisp(tmp_path: Path, target: str) -> None:
    plan = _plan(tmp_path)
    if target == "reels":
        plan = ReferencePlanProjector().project(plan, REELS_9_16, tmp_path / "reels")
        assert plan.motion[1].params["focus_wash"]["focus_asset_ids"] == ["S1:focus"]
    frames = _frames(FFmpegRenderer().render(plan, tmp_path / f"{target}.mp4"), plan.width, plan.height)
    corner = (slice(2, 12), slice(plan.width // 2 - 5, plan.width // 2 + 5))   # empty canvas
    backdrop, focus = _box(plan, "S1:backdrop"), _box(plan, "S1:focus")
    before, washed = frames[20], frames[50]
    assert before[corner].mean() > 250                                   # untouched before the wash
    expected_white = 255 * (1 - 0.42) + 0x9C * 0.42
    assert abs(washed[corner].mean() - expected_white) < 6               # grey wash on the canvas
    assert washed[backdrop][..., 1].mean() > before[backdrop][..., 1].mean() + 35   # backdrop washes toward grey
    assert np.abs(washed[focus].astype(int) - np.array(BLUE)).max() < 24             # focus crisp, untinted
    # The next scene holds the washed picture until its own opener: no crisp flicker.
    held = frames[61]
    assert held[corner].mean() < 245 and held[backdrop][..., 1].mean() > before[backdrop][..., 1].mean() + 35


def test_without_a_wash_the_renderer_output_is_unchanged(tmp_path: Path) -> None:
    plan = _plan(tmp_path, wash=None)
    frames = _frames(FFmpegRenderer().render(plan, tmp_path / "plain.mp4"), plan.width, plan.height)
    assert frames[50][2:12, plan.width // 2 - 5:plan.width // 2 + 5].mean() > 250
    assert abs(frames[50][_box(plan, "S1:backdrop")][..., 0].mean() - RED[0]) < 12


def test_a_wash_without_a_receding_asset_or_focus_on_screen_is_not_executed(tmp_path: Path) -> None:
    plan = _plan(tmp_path, wash={**WASH, "focus_asset_ids": ["S1:focus", "S1:backdrop"]})
    beat = plan.story[0]
    items = plan.composition[0].items
    motion = {(c.beat_id, c.asset_id): c for c in plan.motion}
    assert FFmpegRenderer._focus_wash(plan=plan, beat=beat, ordered_items=items, motion=motion,
                                      segment_start=0.0, duration=2.0) is None
