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
            {"progress": 0.48, "dx": dx, "dy": 0.0, "scale": 1.0, "easing": "linear"},
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
        program=_program(dx=0.04),
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
