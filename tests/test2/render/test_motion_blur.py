"""Visual sprint B1/B3/B4 - velocity-aware directional motion blur.

Motion (or Boundary, for the exits it plans) owns the decision; the renderer smears each
encoded frame along the displacement the element travels during a centred half-frame
exposure, evaluated from the exact expressions it draws. Frames at rest are untouched.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image, ImageDraw

from app.models import (
    CompositionBeat,
    LayoutItem,
    MotionCue,
    MotionSegment,
    PlanProjection,
    RenderPlan,
    SceneBoundaryRelease,
    StoryBeat,
    VisualAsset,
)
from app.motion.motion_blur import MAX_LENGTH, MIN_LENGTH, MOTION_BLUR_SHUTTER, MotionBlurPolicy
from app.render.expression import compile_expression
from app.render.motion import FFmpegMotionAdapter
from app.render.renderer import FFmpegRenderer

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg required")
SPEC = {"owner": "MOTION", "shutter": MOTION_BLUR_SHUTTER, "min_length": MIN_LENGTH, "max_length": MAX_LENGTH}


def _slide(dx: float = 0.3, dy: float = 0.0, *, start: float = 0.6, end: float = 1.1, scale: float = 1.0) -> list:
    """Still entry, then a smoothstep travel over [start, end] held until the beat ends (a
    non-ENTRY segment only owns its own window, so it runs to the beat end and holds)."""
    still = {"name": "s", "keyframes": [{"progress": 0.0, "dx": 0, "dy": 0, "scale": 1.0},
                                        {"progress": 1.0, "dx": 0, "dy": 0, "scale": 1.0}]}
    arrive = (end - start) / (2.0 - start)
    travel = {"name": "travel", "keyframes": [
        {"progress": 0.0, "dx": 0, "dy": 0, "scale": 1.0, "easing": "smoothstep"},
        {"progress": arrive, "dx": dx, "dy": dy, "scale": scale, "easing": "smoothstep"},
        {"progress": 1.0, "dx": dx, "dy": dy, "scale": scale, "easing": "linear"}]}
    return [MotionSegment(phase="ENTRY", start=0.1, end=0.3, program=still),
            MotionSegment(phase="INTERACT", start=start, end=2.0, program=travel)]


def _cue(segments, **params) -> MotionCue:
    return MotionCue(beat_id="b", asset_id="A", kind="program_v3", start=0.1, end=0.3,
                     params={"engine_version": 3, **params}, segments=segments)


def _composition() -> list[CompositionBeat]:
    return [CompositionBeat(beat_id="b", items=[LayoutItem(asset_id="A", x=0.3, y=0.5, width=0.2, height=0.3)])]


# ------------------------------------------------------------------ expression evaluator
def test_evaluator_reproduces_the_drawn_expression() -> None:
    x_expr, _ = FFmpegMotionAdapter().position_expressions(
        cue=_cue(_slide()), target_x=100, target_y=0, canvas_width=1000, canvas_height=500,
        segment_start=0.0, segment_duration=2.0)
    x = compile_expression(x_expr)
    for t, p in ((0.5, 0.0), (0.85, 0.5), (1.0, 0.8), (1.5, 1.0)):
        smooth = 3 * p * p - 2 * p ** 3
        assert x(t) == pytest.approx(100 + 300 * smooth, abs=1e-6)


@pytest.mark.parametrize("text", ["__import__('os')", "t.real", "[1, 2]", "lambda: 1", "t if t else 0", "a"])
def test_evaluator_rejects_anything_outside_the_generated_subset(text: str) -> None:
    with pytest.raises((ValueError, SyntaxError)):
        compile_expression(text)


# ------------------------------------------------------------------ Motion ownership
def test_policy_blurs_visible_travel_and_abstains_otherwise() -> None:
    cues = [
        _cue(_slide(0.3)),                                                     # fast slide
        _cue(_slide(0.0, scale=1.12)).model_copy(update={"asset_id": "B"}),    # scale only
        _cue(_slide(0.001)).model_copy(update={"asset_id": "C"}),              # imperceptible
        _cue(_slide(0.3), render_constraints={"geometry_lock": "authored_footprint"}).model_copy(
            update={"asset_id": "D"}),
        _cue(_slide(0.3), family_follow="A").model_copy(update={"asset_id": "E"}),
    ]
    composition = [CompositionBeat(beat_id="b", items=[
        LayoutItem(asset_id=name, x=0.3, y=0.5, width=0.2, height=0.3) for name in "ABCDE"])]
    policy = MotionBlurPolicy()
    out = policy.plan(cues, composition, width=1920, height=1080, fps=30)
    reasons = {row.asset_id: row.reason for row in policy.decisions}
    assert reasons == {"A": "blur:visible_smear", "B": "abstain:below_visible_smear",
                       "C": "abstain:below_visible_smear", "D": "abstain:geometry_locked",
                       "E": "abstain:family_follows_leader_transform"}
    spec = out[0].params["motion_blur"]
    assert spec["owner"] == "MOTION" and spec["shutter"] == MOTION_BLUR_SHUTTER
    # peak smear of a 0.3-width smoothstep slide in 0.5 s at 180 degrees: 1.5 * 0.3 * 1920 / 0.5 / 60 px
    # peak speed (1.5 x mean of 0.3 W over 0.5 s) times the exposure (shutter / fps)
    assert spec["peak_length"] * 1080 == pytest.approx(1.5 * 0.3 * 1920 / 0.5 * MOTION_BLUR_SHUTTER / 30, rel=0.03)
    assert all("motion_blur" not in cue.params for cue in out[1:])


# ------------------------------------------------------------------ per-frame exposure
def _plan_facts(*, height: int = 1080, projection=None):
    return SimpleNamespace(fps=30, height=height, width=1920 if projection is None else 1080, projection=projection)


@pytest.mark.parametrize("dx,dy,angle", [(0.3, 0.0, 0.0), (0.0, 0.3, 90.0), (0.2, 0.2 * 1920 / 1080, 45.0),
                                          (-0.3, 0.0, 0.0)])
def test_each_frame_smears_along_its_own_displacement(dx: float, dy: float, angle: float) -> None:
    adapter = FFmpegMotionAdapter()
    x_expr, y_expr = adapter.position_expressions(
        cue=_cue(_slide(dx, dy)), target_x=500, target_y=300, canvas_width=1920, canvas_height=1080,
        segment_start=0.0, segment_duration=2.0)
    windows = FFmpegRenderer._motion_blur_windows(
        plan=_plan_facts(), spec=SPEC, x_expr=x_expr, y_expr=y_expr, scale_expr="1", box=(384, 324),
        visible=(0.0, 2.0), duration=2.0)
    assert len(windows) == 1
    frames = windows[0]["frames"]
    assert 0.6 * 30 <= frames[0][0] and frames[-1][0] <= 1.1 * 30      # only while it travels
    assert all(abs(((row[2] - angle + 90) % 180) - 90) < 0.5 for row in frames)
    peak = max(row[1] for row in frames)
    middle = min(frames, key=lambda row: abs(row[0] - 0.85 * 30))
    assert middle[1] == pytest.approx(peak, rel=0.05)                 # strongest at peak speed
    assert frames[0][1] < 0.5 * peak and frames[-1][1] < 0.5 * peak  # resolving at both ends


def test_projected_target_measures_lengths_against_the_projected_content() -> None:
    projection = PlanProjection(reference_width=1920, reference_height=1080, scale=0.5625, offset_x=0, offset_y=656)
    x_expr = "500+(200*if(lt(t,0.6),0,if(lt(t,1.1),(t-0.6)/0.5,1)))"
    landscape = FFmpegRenderer._motion_blur_windows(
        plan=_plan_facts(), spec=SPEC, x_expr=x_expr, y_expr="300", scale_expr="1", box=(100, 100),
        visible=(0.0, 2.0), duration=2.0)
    projected = FFmpegRenderer._motion_blur_windows(
        plan=_plan_facts(height=1920, projection=projection), spec=SPEC, x_expr=x_expr, y_expr="300",
        scale_expr="1", box=(100, 100), visible=(0.0, 2.0), duration=2.0)
    # identical output-pixel travel: identical smear, same frames
    assert [row[0] for row in landscape[0]["frames"]] == [row[0] for row in projected[0]["frames"]]
    assert landscape[0]["frames"][5][1] == pytest.approx(projected[0]["frames"][5][1])


def test_no_spec_or_foreign_owner_means_no_blur() -> None:
    for spec in (None, {}, {**SPEC, "owner": "TEXT"}, {**SPEC, "shutter": 0}):
        assert FFmpegRenderer._motion_blur_windows(
            plan=_plan_facts(), spec=spec, x_expr="t*1000", y_expr="0", scale_expr="1", box=(10, 10),
            visible=(0.0, 1.0), duration=1.0) == []


def test_boundary_owns_the_blur_of_its_planned_exits_only() -> None:
    exits = SceneBoundaryRelease(beat_id="b2", from_beat_id="b1", mode="CRISP_HANDOFF", reason="r",
                                 exit_starts={"A": 1.0}, exit_motion_blur={**SPEC, "owner": "BOUNDARY"})
    assert exits.model_dump()["exit_motion_blur"]["owner"] == "BOUNDARY"
    cut = SceneBoundaryRelease(beat_id="b2", from_beat_id="b1", reason="r")
    assert "exit_motion_blur" not in cut.model_dump()  # absent, not an empty field, on plain cuts


# ------------------------------------------------------------------ encoded frames
def _sprite(path: Path) -> Path:
    """Opaque light bars on transparent black, exactly the Composition box size (384 x 324
    on the 1920 x 1080 default canvas), so the box fit is a pass-through and adds no edge
    fringe: a correct smear over white is a light/white mix, a straight-alpha one is not."""
    image = Image.new("RGBA", (384, 324), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    for x in range(40, 344, 50):
        draw.rectangle((x, 40, x + 22, 284), fill=(250, 230, 120, 255))
    image.save(path)
    return path


def _encoded_plan(tmp_path: Path, *, blur: bool) -> RenderPlan:
    asset = VisualAsset(id="A", scene_id="S", role="primary", image_path=_sprite(tmp_path / "sprite.png"),
                        extraction_method="test")
    story = [StoryBeat(id="b", scene_id="S", start=0.0, end=2.0, narration="a", action="REVEAL",
                       primary_asset_ids=["A"])]
    cue = _cue(_slide(0.35), **({"motion_blur": SPEC} if blur else {}))
    return RenderPlan(duration=2.0, story=story, composition=_composition(), motion=[cue], assets=[asset])


class _Lossless(FFmpegRenderer):
    """Same filtergraph, lossless encode: decoded frames equal the filter output exactly."""

    def _encode_args(self, filters, target, fps, frame_count):
        args = super()._encode_args(filters, target, fps, frame_count)
        index = args.index("-crf")
        return args[:index] + ["-qp", "0"] + args[index + 2:]


def _frames(video: Path, plan: RenderPlan) -> np.ndarray:
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(video), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, plan.height, plan.width, 3).astype(int)


@needs_ffmpeg
def test_encoded_blur_is_directional_resolves_sharp_and_has_no_halo(tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    sharp_plan, blur_plan = _encoded_plan(tmp_path / "a", blur=False), _encoded_plan(tmp_path / "b", blur=True)
    sharp = _frames(_Lossless().render(sharp_plan, tmp_path / "a" / "v.mp4"), sharp_plan)
    blurred = _frames(_Lossless().render(blur_plan, tmp_path / "b" / "v.mp4"), blur_plan)
    assert sharp.shape == blurred.shape
    moving = [n for n in range(len(sharp)) if not np.array_equal(sharp[n], blurred[n])]
    assert moving, "the travelling frames must be smeared"
    assert min(moving) >= round(0.6 * 30) and max(moving) <= round(1.1 * 30)  # rest frames byte-identical
    # the element is drawn on every frame - a branch's end of stream once swallowed the
    # window's last frame (and every one-frame window: near-white handoff frames)
    for n in range(len(sharp)):
        ink_sharp = int((np.abs(sharp[n] - 255).sum(axis=2) > 30).sum())
        ink_blurred = int((np.abs(blurred[n] - 255).sum(axis=2) > 30).sum())
        assert ink_blurred >= 0.8 * ink_sharp, f"element missing on frame {n}"
    middle = round(0.85 * 30)                                                  # peak speed
    # premultiplied smear: the trail (pixels that are canvas in the sharp frame) only mixes
    # the sprite with the white canvas, so it is never darker than the sprite. A straight-
    # alpha blur pulls the transparent pixels' black into it: a dark halo (~40 levels below
    # the sprite in this fixture).
    def luma(frame):
        return 0.299 * frame[..., 0] + 0.587 * frame[..., 1] + 0.114 * frame[..., 2]

    sharp_luma, blurred_luma = luma(sharp[middle]), luma(blurred[middle])
    sprite = np.median(sharp_luma[sharp_luma < 245])
    trail = (sharp_luma >= 250) & (np.abs(blurred_luma - sharp_luma) > 2)
    assert trail.sum() > 2000
    assert blurred_luma[trail].min() >= sprite - 8
    assert blurred[middle][:, :100].min() >= 250    # canvas far from the element untouched
    # directional: edges across the motion are smeared, edges along it are kept
    gray_s, gray_b = sharp[middle].mean(axis=2), blurred[middle].mean(axis=2)
    gx_s, gx_b = np.abs(np.diff(gray_s, axis=1)).sum(), np.abs(np.diff(gray_b, axis=1)).sum()
    gy_s, gy_b = np.abs(np.diff(gray_s, axis=0)).sum(), np.abs(np.diff(gray_b, axis=0)).sum()
    assert gx_b < 0.85 * gx_s
    assert gy_b > 0.9 * gy_s
