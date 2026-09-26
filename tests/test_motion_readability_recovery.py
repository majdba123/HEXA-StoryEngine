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
from app.motion.timing import GOLDEN_MAJOR, semantic_readability_floor
from app.qa import RenderedMotionQA
from app.recovery.manager import RecoveryManager
from app.recovery.motion_readability import repair_motion_readability
from app.recovery.policy import FailureDisposition, failure_policy
from app.render.renderer import FFmpegRenderer


def _program(dx: float, *, active_duration: float) -> dict:
    return {
        "name": "reference_target_react",
        "settle_progress": 1.0,
        "semantic_active_duration": active_duration,
        "semantic_peak_progress": GOLDEN_MAJOR,
        "keyframes": [
            {
                "progress": 0.0,
                "dx": 0.0,
                "dy": 0.0,
                "scale": 1.0,
                "easing": "linear",
            },
            {
                "progress": GOLDEN_MAJOR,
                "dx": dx,
                "dy": 0.0,
                "scale": 1.0,
                "easing": "ease_in_out_cubic",
            },
            {
                "progress": 1.0,
                "dx": 0.0,
                "dy": 0.0,
                "scale": 1.0,
                "easing": "linear",
            },
        ],
    }


def _plan(asset_path: Path) -> RenderPlan:
    beat = StoryBeat(
        id="beat-010",
        scene_id="SCENE_010",
        start=0.0,
        end=1.2,
        narration="reaction",
        primary_asset_ids=["SCENE_010:asset-01"],
        support_asset_ids=["SCENE_010:asset-03"],
        action="REVEAL_DETAIL",
    )
    weak = MotionSegment(
        phase="REACT",
        start=0.30,
        end=0.70,
        program=_program(0.00693, active_duration=0.22),
        semantic_event_id="E2",
        semantic_action="REACT",
        involvement="TARGET",
        source_asset_id="SCENE_010:asset-01",
        target_asset_id="SCENE_010:asset-03",
    )
    stable = MotionSegment(
        phase="INTERACT",
        start=0.20,
        end=0.60,
        program=_program(0.015, active_duration=0.30),
        semantic_event_id="E2",
        semantic_action="CONNECT",
        involvement="SOURCE",
        source_asset_id="SCENE_010:asset-01",
        target_asset_id="SCENE_010:asset-03",
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
                items=[
                    LayoutItem(
                        asset_id="SCENE_010:asset-01",
                        x=0.25,
                        y=0.5,
                        width=0.20,
                        height=0.30,
                    ),
                    LayoutItem(
                        asset_id="SCENE_010:asset-03",
                        x=0.70,
                        y=0.5,
                        width=0.20,
                        height=0.30,
                    ),
                ],
            )
        ],
        motion=[
            MotionCue(
                beat_id=beat.id,
                asset_id="SCENE_010:asset-01",
                kind="program_v3",
                start=0.0,
                end=0.2,
                params={},
                segments=[stable],
            ),
            MotionCue(
                beat_id=beat.id,
                asset_id="SCENE_010:asset-03",
                kind="program_v3",
                start=0.0,
                end=0.2,
                params={},
                segments=[weak],
            ),
        ],
        assets=[
            VisualAsset(
                id="SCENE_010:asset-01",
                scene_id="SCENE_010",
                role="primary",
                image_path=asset_path,
                extraction_method="test",
            ),
            VisualAsset(
                id="SCENE_010:asset-03",
                scene_id="SCENE_010",
                role="support",
                image_path=asset_path,
                extraction_method="test",
            ),
        ],
    )


def _asset(path: Path) -> None:
    image = Image.new("RGBA", (180, 180), (255, 255, 255, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(
        (18, 18, 162, 162),
        radius=18,
        fill=(50, 80, 180, 255),
    )
    image.save(path)


def test_motion_floor_is_explicit_bounded_recovery(tmp_path: Path) -> None:
    policy = failure_policy("MOTION_BELOW_PERCEPTUAL_FLOOR")
    assert policy is not None
    assert policy.disposition == FailureDisposition.RECOVER

    manager = RecoveryManager(tmp_path)
    result = manager.handle(
        code="MOTION_BELOW_PERCEPTUAL_FLOOR",
        context={"beat_id": "beat-010"},
        attempt=1,
    )
    assert result is not None
    assert result.invalidate_from_stage == "motion_segment"


def test_readability_recovery_changes_only_reported_underfloor_segment(
    tmp_path: Path,
) -> None:
    asset = tmp_path / "asset.png"
    _asset(asset)
    plan = _plan(asset)
    stable_before = plan.motion[0]
    weak_before = plan.motion[1].segments[0]

    class Violation:
        code = "MOTION_BELOW_PERCEPTUAL_FLOOR"
        beat_id = "beat-010"
        asset_id = "SCENE_010:asset-03"
        phase = "REACT"

    repaired = repair_motion_readability(
        plan,
        violations=[Violation()],
        attempt=1,
    )

    assert repaired.repaired_segments == 1
    assert repaired.plan.motion[0] == stable_before
    weak_after = repaired.plan.motion[1].segments[0]
    assert weak_after.start == weak_before.start
    assert weak_after.end == weak_before.end
    assert weak_after.semantic_event_id == weak_before.semantic_event_id
    assert weak_after.relationship == weak_before.relationship
    assert weak_after.program["readability_recovery"] is True

    activity = max(
        (float(frame["dx"]) ** 2 + float(frame["dy"]) ** 2) ** 0.5
        for frame in weak_after.program["keyframes"]
    )
    floor = semantic_readability_floor(
        "REACT",
        item_width=0.20,
        item_height=0.30,
        duration=0.22,
        frame_width=320,
        frame_height=180,
    )
    assert activity >= floor


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg required")
def test_recovered_segment_passes_rendered_motion_qa(tmp_path: Path) -> None:
    asset = tmp_path / "asset.png"
    _asset(asset)
    plan = _plan(asset)
    qa = RenderedMotionQA()
    renderer = FFmpegRenderer("ffmpeg")

    weak_video = renderer.render(plan, tmp_path / "weak.mp4")
    weak_report = qa.inspect(video=weak_video, plan=plan)
    floor_rows = [
        row
        for row in weak_report.violations
        if row.code == "MOTION_BELOW_PERCEPTUAL_FLOOR"
    ]
    assert floor_rows

    repaired = repair_motion_readability(
        plan,
        violations=floor_rows,
        attempt=1,
    )
    assert repaired.repaired_segments == 1
    recovered_video = renderer.render(
        repaired.plan,
        tmp_path / "recovered.mp4",
    )
    recovered_report = qa.inspect(
        video=recovered_video,
        plan=repaired.plan,
    )

    assert recovered_report.ok, recovered_report.violations
