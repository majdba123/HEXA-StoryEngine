"""Cinematic VNext2 - a locked Pass2 layer bound to its primary is drawn with the primary's
transform (encoded frames): during the primary's scale pulse the two layers stay
pixel-adjacent, exactly as authored. Without the binding the layer stays put (v6)."""
from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from app.models import AssetActivation, CompositionBeat, LayoutItem, MotionCue, MotionSegment, RenderPlan, StoryBeat, VisualAsset
from app.render.renderer import FFmpegRenderer

BLUE, RED = (30, 60, 220), (220, 30, 30)


def _part(path: Path, colour, columns: range) -> Path:
    image = Image.new("RGBA", (200, 300), (0, 0, 0, 0))
    for x in columns:
        for y in range(300):
            image.putpixel((x, y), (*colour, 255))
    image.save(path)
    return path


def _plan(tmp_path: Path, *, bound: bool) -> RenderPlan:
    main = _part(tmp_path / "main.png", BLUE, range(40, 200))    # the picture
    layer = _part(tmp_path / "layer.png", RED, range(0, 40))     # its detached outer piece
    assets = [VisualAsset(id="F", scene_id="S", role="primary", image_path=main, extraction_method="test"),
              VisualAsset(id="F:secondary-01", scene_id="S", role="primary", image_path=layer, extraction_method="test",
                          parent_asset_id="F", asset_family_id="F")]
    story = [StoryBeat(id="b", scene_id="S", start=0.0, end=2.0, narration="a", action="REVEAL", primary_asset_ids=["F"],
                       asset_activations=[AssetActivation(asset_id="F", semantic_unit_id="U"),
                                          AssetActivation(asset_id="F:secondary-01", semantic_unit_id="U")])]
    box = dict(x=0.5, y=0.5, width=0.2, height=0.5)
    composition = [CompositionBeat(beat_id="b", items=[LayoutItem(asset_id="F", **box),
                                                        LayoutItem(asset_id="F:secondary-01", z=1, **box)])]
    still = {"name": "s", "keyframes": [{"progress": 0.0, "dx": 0, "dy": 0, "scale": 1.0},
                                        {"progress": 1.0, "dx": 0, "dy": 0, "scale": 1.0}]}
    pulse = MotionSegment(phase="ESTABLISH", start=0.8, end=1.4, semantic_action="HERO_EMPHASIS", program={
        "name": "hero_settle_emphasis", "keyframes": [
            {"progress": 0.0, "dx": 0, "dy": 0, "scale": 1.0, "easing": "smoothstep"},
            {"progress": 0.5, "dx": 0, "dy": 0, "scale": 1.12, "easing": "smoothstep"},
            {"progress": 1.0, "dx": 0, "dy": 0, "scale": 1.0, "easing": "smoothstep"}]})
    layer_params = {"engine_version": 3, "render_constraints": {"geometry_lock": "authored_footprint"}}
    if bound:
        layer_params["family_follow"] = "F"
    motion = [
        MotionCue(beat_id="b", asset_id="F", kind="program_v3", start=0.1, end=0.3, params={"engine_version": 3},
                  segments=[MotionSegment(phase="ENTRY", start=0.1, end=0.3, program=still), pulse]),
        MotionCue(beat_id="b", asset_id="F:secondary-01", kind="program_v3", start=0.1, end=0.3, params=layer_params,
                  segments=[MotionSegment(phase="ENTRY", start=0.1, end=0.3, program=still)]),
    ]
    return RenderPlan(duration=2.0, story=story, composition=composition, motion=motion, assets=assets)


def _frame(video: Path, plan: RenderPlan, index: int) -> np.ndarray:
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(video), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, plan.height, plan.width, 3)[index]


def _columns(frame: np.ndarray, colour) -> tuple[int, int]:
    row = frame[frame.shape[0] // 2].astype(int)
    hits = np.nonzero(np.abs(row - np.array(colour)).sum(axis=1) < 90)[0]
    return int(hits.min()), int(hits.max())


@pytest.mark.parametrize("bound", [True, False])
def test_a_bound_layer_pulses_with_its_primary(tmp_path: Path, bound: bool) -> None:
    plan = _plan(tmp_path, bound=bound)
    video = FFmpegRenderer().render(plan, tmp_path / f"family-{bound}.mp4")
    rest, peak = _frame(video, plan, 20), _frame(video, plan, 33)       # 0.67 s rest, 1.1 s pulse peak
    blue_rest, red_rest = _columns(rest, BLUE), _columns(rest, RED)
    blue_peak, red_peak = _columns(peak, BLUE), _columns(peak, RED)
    assert abs(blue_rest[0] - red_rest[1]) <= 3                          # authored: the pieces touch
    assert blue_peak[1] - blue_peak[0] > blue_rest[1] - blue_rest[0] + 10  # the primary pulses
    if bound:
        assert red_peak[0] < red_rest[0] - 10                           # the outer piece moves outward with it
        assert abs(blue_peak[0] - red_peak[1]) <= 3                      # still one picture at the peak
    else:
        assert abs(red_peak[0] - red_rest[0]) <= 2                       # v6: the locked piece stays put
