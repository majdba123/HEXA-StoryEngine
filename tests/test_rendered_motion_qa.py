from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from app.models import (
    CompositionBeat,
    LayoutItem,
    MotionCue,
    MotionSegment,
    RenderPlan,
    StoryBeat,
    VisualAsset,
)
from app.motion.timing import (
    GOLDEN_MAJOR,
    GOLDEN_MINOR,
    max_comfort_displacement,
    semantic_readability_floor,
)
from app.qa import RenderedMotionQA
from app.render.renderer import FFmpegRenderer


def _asset(path: Path) -> None:
    image = Image.new("RGBA", (180, 180), (255, 255, 255, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((18, 18, 162, 162), radius=18, fill=(215, 55, 55, 255))
    image.save(path)


def _program(dx: float = 0.0) -> dict:
    return {
        "name": "test",
        "settle_progress": 1.0,
        "keyframes": [
            {"progress": 0.0, "dx": 0.0, "dy": 0.0, "scale": 1.0, "easing": "linear"},
            {
                "progress": GOLDEN_MAJOR,
                "dx": dx,
                "dy": 0.0,
                "scale": 1.0,
                "easing": "ease_in_out_cubic",
            },
            {"progress": 1.0, "dx": 0.0, "dy": 0.0, "scale": 1.0, "easing": "linear"},
        ],
    }


def _plan(path: Path, *, rendered_segment: bool) -> RenderPlan:
    beat = StoryBeat(
        id="beat",
        scene_id="scene",
        start=0.0,
        end=1.2,
        audio_start=0.0,
        audio_end=1.2,
        narration="relation",
        primary_asset_ids=["asset"],
        action="REVEAL_DETAIL",
    )
    segment = MotionSegment(
        phase="INTERACT",
        start=0.40,
        end=0.82,
        program=_program(dx=0.0215),
        semantic_event_id="E1",
        semantic_action="CONNECT",
        involvement="SOURCE",
        source_asset_id="asset",
        target_asset_id="target",
    )
    cue = MotionCue(
        beat_id=beat.id,
        asset_id="asset",
        kind="program_v3",
        start=0.0,
        end=0.18,
        params={"engine_version": 3, "program": _program(dx=0.0)},
        segments=[segment] if rendered_segment else [],
    )
    return RenderPlan(
        width=320,
        height=180,
        fps=30,
        duration=1.2,
        story=[beat],
        composition=[
            CompositionBeat(
                beat_id=beat.id,
                items=[LayoutItem(asset_id="asset", x=0.5, y=0.5, width=0.42, height=0.64)],
            )
        ],
        motion=[cue],
        assets=[
            VisualAsset(
                id="asset",
                scene_id="scene",
                role="primary",
                image_path=path,
                extraction_method="test",
            )
        ],
    )


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg required")
def test_rendered_motion_qa_proves_encoded_semantic_segment_is_active(tmp_path: Path) -> None:
    asset = tmp_path / "asset.png"
    _asset(asset)
    plan = _plan(asset, rendered_segment=True)
    video = tmp_path / "active.mp4"

    FFmpegRenderer("ffmpeg").render(plan, video)
    report = RenderedMotionQA().inspect(video=video, plan=plan)

    assert report.ok, report.violations
    assert report.checked_segments == 1


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg required")
def test_rendered_motion_qa_rejects_metadata_only_motion(tmp_path: Path) -> None:
    asset = tmp_path / "asset.png"
    _asset(asset)
    expected_plan = _plan(asset, rendered_segment=True)
    static_plan = _plan(asset, rendered_segment=False)
    video = tmp_path / "static.mp4"

    FFmpegRenderer("ffmpeg").render(static_plan, video)
    report = RenderedMotionQA().inspect(video=video, plan=expected_plan)

    assert not report.ok
    assert any(row.code == "RENDERED_SEGMENT_INACTIVE" for row in report.violations)


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg required")
def test_rendered_motion_qa_rejects_visually_tiny_motion(tmp_path: Path) -> None:
    asset = tmp_path / "asset.png"
    _asset(asset)
    plan = _plan(asset, rendered_segment=True)
    cue = plan.motion[0]
    weak_segment = cue.segments[0].model_copy(update={"program": _program(dx=0.005)})
    plan = plan.model_copy(update={
        "motion": [cue.model_copy(update={"segments": [weak_segment]})],
    })
    video = tmp_path / "weak.mp4"
    FFmpegRenderer("ffmpeg").render(plan, video)
    report = RenderedMotionQA().inspect(video=video, plan=plan)
    assert not report.ok
    assert any(row.code == "MOTION_BELOW_PERCEPTUAL_FLOOR" for row in report.violations)



@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg required")
def test_collision_limited_motion_may_go_below_floor_but_must_render(tmp_path: Path) -> None:
    asset = tmp_path / "asset.png"
    _asset(asset)
    plan = _plan(asset, rendered_segment=True)
    cue = plan.motion[0]
    program = _program(dx=0.015)
    program["collision_limited"] = True
    program["collision_gain"] = 0.5
    segment = cue.segments[0].model_copy(update={"program": program})
    plan = plan.model_copy(update={
        "motion": [cue.model_copy(update={"segments": [segment]})],
    })
    video = tmp_path / "collision-limited.mp4"
    FFmpegRenderer("ffmpeg").render(plan, video)
    report = RenderedMotionQA().inspect(video=video, plan=plan)

    assert report.ok, report.violations
    assert report.checked_segments == 1


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg required")
def test_rendered_exit_moves_then_disappears(tmp_path: Path) -> None:
    asset = tmp_path / "asset.png"
    _asset(asset)
    plan = _plan(asset, rendered_segment=True)
    cue = plan.motion[0]
    exit_program = {
        "name": "semantic_release_exit",
        "settle_progress": 1.0,
        "keyframes": [
            {"progress": 0.0, "dx": 0.0, "dy": 0.0, "scale": 1.0, "easing": "linear"},
            {"progress": 1.0, "dx": 0.06, "dy": 0.0, "scale": 0.95, "easing": "linear"},
        ],
    }
    exit_segment = cue.segments[0].model_copy(update={
        "phase": "EXIT", "start": 0.45, "end": 0.90, "program": exit_program,
    })
    plan = plan.model_copy(update={
        "motion": [cue.model_copy(update={"segments": [exit_segment]})],
    })
    video = tmp_path / "exit.mp4"
    FFmpegRenderer("ffmpeg").render(plan, video)
    report = RenderedMotionQA().inspect(video=video, plan=plan)
    assert report.ok, report.violations

    import cv2
    capture = cv2.VideoCapture(str(video))
    capture.set(cv2.CAP_PROP_POS_MSEC, 1000.0)
    ok, frame = capture.read()
    capture.release()
    assert ok and frame is not None
    roi = frame[45:135, 95:225]
    assert float(roi.mean()) > 245.0


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg required")
def test_rendered_motion_qa_rejects_rushed_motion_even_when_visible(tmp_path: Path) -> None:
    asset = tmp_path / "asset.png"
    _asset(asset)
    plan = _plan(asset, rendered_segment=True)
    cue = plan.motion[0]
    rushed = cue.segments[0].model_copy(update={
        "start": 0.40,
        "end": 0.52,
        "program": _program(dx=0.04),
    })
    plan = plan.model_copy(update={
        "motion": [cue.model_copy(update={"segments": [rushed]})],
    })
    video = tmp_path / "rushed.mp4"
    FFmpegRenderer("ffmpeg").render(plan, video)
    report = RenderedMotionQA().inspect(video=video, plan=plan)
    assert not report.ok
    assert any(row.code == "MOTION_TOO_FAST" for row in report.violations)


def test_short_react_readability_floor_never_requires_rushed_motion() -> None:
    duration = 0.19
    width = 640
    floor = RenderedMotionQA._perceptual_floor_px(
        phase="REACT",
        width=width,
        height=360,
        item_width=0.18,
        item_height=0.28,
        duration=duration,
    )
    comfort_budget = width * max_comfort_displacement(
        "REACT",
        duration * GOLDEN_MINOR,
    )
    assert floor <= comfort_budget + 1e-9


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg required")
def test_rendered_motion_qa_skips_transform_check_for_geometry_locked_asset(tmp_path: Path) -> None:
    asset = tmp_path / "asset.png"
    _asset(asset)
    plan = _plan(asset, rendered_segment=True)
    cue = plan.motion[0]
    locked = cue.model_copy(update={
        "params": {
            **cue.params,
            "render_constraints": {
                "geometry_lock": "authored_footprint",
                "reveal_mode": "alpha_only",
            },
        }
    })
    plan = plan.model_copy(update={"motion": [locked]})
    video = tmp_path / "locked.mp4"

    FFmpegRenderer("ffmpeg").render(plan, video)
    report = RenderedMotionQA().inspect(video=video, plan=plan)

    assert report.ok, report.violations
    assert report.checked_segments == 0
    assert report.skipped_static_segments == 1



def test_directional_comfort_budget_uses_dominant_vertical_translation_channel() -> None:
    duration = 0.50
    segment = MotionSegment(
        phase="REACT",
        start=1.0,
        end=1.0 + duration,
        program={
            "name": "semantic_segment_react",
            "keyframes": [
                {"progress": 0.0, "dx": 0.0, "dy": 0.0, "scale": 1.0, "easing": "linear"},
                {
                    "progress": GOLDEN_MAJOR,
                    "dx": 0.0,
                    "dy": -0.022,
                    "scale": 1.003,
                    "easing": "ease_in_out_cubic",
                },
                {"progress": 1.0, "dx": 0.0, "dy": 0.0, "scale": 1.0, "easing": "smoothstep"},
            ],
        },
        semantic_event_id="E1",
        semantic_action="REACT",
        involvement="TARGET",
    )

    budget = RenderedMotionQA._directional_comfort_budget_px(
        segment,
        duration=duration,
        width=1920,
        height=1080,
        item_width=0.20,
        item_height=0.30,
    )
    normalized_budget = max_comfort_displacement(
        "REACT",
        duration * GOLDEN_MINOR,
    )

    assert budget == pytest.approx(normalized_budget * 1080, abs=1e-6)


def test_directional_comfort_budget_uses_scale_channel_when_scale_is_visually_dominant() -> None:
    duration = 0.50
    segment = MotionSegment(
        phase="REACT",
        start=1.0,
        end=1.0 + duration,
        program={
            "name": "semantic_segment_react_scale",
            "keyframes": [
                {"progress": 0.0, "dx": 0.0, "dy": 0.0, "scale": 1.0, "easing": "linear"},
                {
                    "progress": GOLDEN_MAJOR,
                    "dx": 0.0,
                    "dy": -0.002,
                    "scale": 1.05,
                    "easing": "ease_in_out_cubic",
                },
                {"progress": 1.0, "dx": 0.0, "dy": 0.0, "scale": 1.0, "easing": "smoothstep"},
            ],
        },
        semantic_event_id="E1",
        semantic_action="REACT",
        involvement="TARGET",
    )

    budget = RenderedMotionQA._directional_comfort_budget_px(
        segment,
        duration=duration,
        width=1920,
        height=1080,
        item_width=0.20,
        item_height=0.30,
    )
    normalized_budget = max_comfort_displacement(
        "REACT",
        duration * GOLDEN_MINOR,
    )
    asset_extent = 0.20
    asset_px = min(1920 * 0.20, 1080 * 0.30)

    assert budget == pytest.approx(
        normalized_budget * (asset_px / asset_extent),
        abs=1e-6,
    )



def test_semantic_react_shared_floor_matches_planner_composition_space() -> None:
    duration = 0.36
    item_width = 0.20623007438894797
    item_height = 0.32093517534537724
    normalized_floor = semantic_readability_floor(
        "REACT",
        item_width=item_width,
        item_height=item_height,
        duration=duration,
    )
    comfort_cap = max_comfort_displacement(
        "REACT",
        duration * GOLDEN_MINOR,
    )

    assert normalized_floor == pytest.approx(comfort_cap, abs=1e-9)


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg required")
def test_vertical_react_at_shared_floor_survives_encoded_qa(tmp_path: Path) -> None:
    asset = tmp_path / "vertical-react.png"
    _asset(asset)
    plan = _plan(asset, rendered_segment=True).model_copy(update={
        "width": 640,
        "height": 360,
    })
    cue = plan.motion[0]
    duration = 0.36
    floor = semantic_readability_floor(
        "REACT",
        item_width=0.20623007438894797,
        item_height=0.32093517534537724,
        duration=duration,
    )
    program = {
        "name": "semantic_segment_react_vertical",
        "settle_progress": 1.0,
        "keyframes": [
            {
                "progress": 0.0,
                "dx": 0.0,
                "dy": 0.0,
                "scale": 1.0,
                "easing": "ease_in_out_cubic",
            },
            {
                "progress": GOLDEN_MAJOR,
                "dx": 0.0,
                "dy": -floor,
                "scale": 1.03,
                "easing": "ease_in_out_cubic",
            },
            {
                "progress": 1.0,
                "dx": 0.0,
                "dy": 0.0,
                "scale": 1.0,
                "easing": "smoothstep",
            },
        ],
    }
    segment = cue.segments[0].model_copy(update={
        "phase": "REACT",
        "start": 0.40,
        "end": 0.40 + duration,
        "program": program,
        "involvement": "TARGET",
    })
    composition = plan.composition[0].model_copy(update={
        "items": [
            LayoutItem(
                asset_id="asset",
                x=0.5,
                y=0.5,
                width=0.20623007438894797,
                height=0.32093517534537724,
            )
        ]
    })
    plan = plan.model_copy(update={
        "composition": [composition],
        "motion": [cue.model_copy(update={"segments": [segment]})],
    })

    video = tmp_path / "vertical-react.mp4"
    FFmpegRenderer("ffmpeg").render(plan, video)
    report = RenderedMotionQA().inspect(video=video, plan=plan)

    assert report.ok, report.violations
    assert report.checked_segments == 1



@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg required")
def test_rendered_motion_qa_checks_base_entry_without_semantic_segments(tmp_path: Path) -> None:
    asset = tmp_path / "asset.png"
    _asset(asset)
    plan = _plan(asset, rendered_segment=False)
    cue = plan.motion[0]
    moving = cue.model_copy(update={
        "end": 0.70,
        "params": {**cue.params, "program": _program(dx=0.025)},
    })
    plan = plan.model_copy(update={"motion": [moving]})
    video = tmp_path / "base-entry.mp4"

    FFmpegRenderer("ffmpeg").render(plan, video)
    report = RenderedMotionQA().inspect(video=video, plan=plan)

    assert report.ok, report.violations
    assert report.checked_segments == 1


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg required")
def test_rendered_motion_qa_rejects_missing_encoded_base_entry(tmp_path: Path) -> None:
    asset = tmp_path / "asset.png"
    _asset(asset)
    expected = _plan(asset, rendered_segment=False)
    expected_cue = expected.motion[0]
    expected = expected.model_copy(update={
        "motion": [expected_cue.model_copy(update={
            "end": 0.70,
            "params": {**expected_cue.params, "program": _program(dx=0.025)},
        })],
    })

    static = _plan(asset, rendered_segment=False)
    static_cue = static.motion[0]
    static = static.model_copy(update={
        "motion": [static_cue.model_copy(update={
            "end": 0.70,
            "params": {**static_cue.params, "program": _program(dx=0.0)},
        })],
    })
    video = tmp_path / "base-entry-static.mp4"
    FFmpegRenderer("ffmpeg").render(static, video)

    report = RenderedMotionQA().inspect(video=video, plan=expected)

    assert not report.ok
    assert any(row.code == "RENDERED_SEGMENT_INACTIVE" for row in report.violations)
