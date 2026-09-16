from __future__ import annotations

import shutil
from pathlib import Path

import cv2
import numpy as np
import pytest
from PIL import Image, ImageDraw

from app.models import CompositionBeat, LayoutItem, MotionCue, RenderPlan, StoryBeat, VisualAsset
from app.motion.planner import MotionPlanner
from app.render.renderer import FFmpegRenderer


def _beat(*, action: str, start: float = 0.0, end: float = 3.0) -> StoryBeat:
    return StoryBeat(
        id="beat-1",
        scene_id="scene-1",
        start=start,
        end=end,
        audio_start=start + 0.45,
        audio_end=end - 0.15,
        narration="semantic beat",
        primary_asset_ids=["primary"],
        action=action,
    )


def test_long_emphasis_builds_entry_travel_scale_and_exit_envelope() -> None:
    beat = _beat(action="EMPHASIZE")
    composition = [
        CompositionBeat(
            beat_id=beat.id,
            items=[
                LayoutItem(asset_id="primary", x=0.5, y=0.5, width=0.4, height=0.4),
                LayoutItem(asset_id="support", x=0.72, y=0.5, width=0.2, height=0.2),
            ],
        )
    ]

    cues = MotionPlanner().plan([beat], composition)
    primary = cues[0]

    assert primary.kind == "emphasis_in"
    assert primary.params["motion_version"] == 2
    assert primary.params["entry_scale"] < 1.0
    assert primary.params["travel_enabled"] is True
    assert primary.params["travel_end"] > primary.params["travel_start"] >= primary.end
    assert primary.params["travel_scale"] > 1.0
    assert primary.params["exit_scale"] < 1.0
    assert primary.params["entry_easing"] == "ease_out_cubic"
    assert primary.params["travel_easing"] == "smoothstep"


def test_short_beat_does_not_add_frantic_travel_phase() -> None:
    beat = _beat(action="INTRODUCE", end=0.7)
    beat.audio_start = 0.22
    beat.audio_end = 0.66
    composition = [
        CompositionBeat(
            beat_id=beat.id,
            items=[LayoutItem(asset_id="primary", x=0.5, y=0.5, width=0.4, height=0.4)],
        )
    ]

    cue = MotionPlanner().plan([beat], composition)[0]

    assert cue.kind == "soft_in"
    assert cue.params["travel_enabled"] is False
    assert cue.params["travel_start"] == cue.params["travel_end"] == cue.end
    assert cue.params["travel_dx_ratio"] == 0.0
    assert cue.params["travel_scale"] == 1.0


def test_supports_still_settle_near_same_narration_anchor() -> None:
    beat = _beat(action="HANDOFF")
    composition = [
        CompositionBeat(
            beat_id=beat.id,
            items=[
                LayoutItem(asset_id="primary", x=0.3, y=0.5, width=0.2, height=0.2),
                LayoutItem(asset_id="support-a", x=0.5, y=0.5, width=0.2, height=0.2),
                LayoutItem(asset_id="support-b", x=0.7, y=0.5, width=0.2, height=0.2),
            ],
        )
    ]

    cues = MotionPlanner().plan([beat], composition)
    support_ends = [cue.end for cue in cues[1:]]

    assert max(support_ends) - min(support_ends) <= 0.11
    assert max(support_ends) <= beat.audio_start + 0.13


def _write_rgba_asset(path: Path) -> None:
    image = Image.new("RGBA", (220, 220), (255, 255, 255, 0))
    ImageDraw.Draw(image).rounded_rectangle((12, 12, 208, 208), radius=24, fill=(220, 55, 55, 255))
    image.save(path)


def _foreground_bounds(frame: np.ndarray) -> tuple[int, int, int, int]:
    b, g, r = cv2.split(frame)
    mask = (r > 150) & (g < 130) & (b < 130)
    ys, xs = np.where(mask)
    assert len(xs) > 0
    return int(xs.min()), int(xs.max()), int(ys.min()), int(ys.max())


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg required")
def test_renderer_executes_in_frame_travel_and_scale(tmp_path: Path) -> None:
    asset_path = tmp_path / "asset.png"
    _write_rgba_asset(asset_path)
    beat = StoryBeat(
        id="beat-1",
        scene_id="scene-1",
        start=0.0,
        end=1.5,
        audio_start=0.25,
        audio_end=1.35,
        narration="motion",
        primary_asset_ids=["asset-1"],
        action="EMPHASIZE",
    )
    cue = MotionCue(
        beat_id=beat.id,
        asset_id="asset-1",
        kind="emphasis_in",
        start=0.0,
        end=0.30,
        params={
            "motion_version": 2,
            "entry_dx_ratio": 0.0,
            "entry_dy_ratio": 0.10,
            "entry_scale": 0.72,
            "travel_enabled": True,
            "travel_start": 0.40,
            "travel_end": 1.20,
            "travel_dx_ratio": 0.12,
            "travel_dy_ratio": -0.04,
            "travel_scale": 1.08,
            "exit_dx_ratio": -0.10,
            "exit_dy_ratio": 0.0,
            "exit_scale": 0.95,
        },
    )
    plan = RenderPlan(
        width=640,
        height=360,
        fps=30,
        duration=1.5,
        story=[beat],
        composition=[
            CompositionBeat(
                beat_id=beat.id,
                items=[LayoutItem(asset_id="asset-1", x=0.5, y=0.5, width=0.42, height=0.62)],
            )
        ],
        motion=[cue],
        assets=[
            VisualAsset(
                id="asset-1",
                scene_id="scene-1",
                role="primary",
                image_path=asset_path,
                extraction_method="test",
            )
        ],
    )

    output = tmp_path / "motion.mp4"
    FFmpegRenderer("ffmpeg").render(plan, output)
    capture = cv2.VideoCapture(str(output))
    assert capture.isOpened()
    frames: dict[int, np.ndarray] = {}
    for index in range(45):
        ok, frame = capture.read()
        assert ok
        if index in {6, 18, 35}:
            frames[index] = frame
    capture.release()

    early = _foreground_bounds(frames[6])
    middle = _foreground_bounds(frames[18])
    late = _foreground_bounds(frames[35])
    early_width = early[1] - early[0] + 1
    late_width = late[1] - late[0] + 1
    early_center_x = (early[0] + early[1]) / 2
    middle_center_x = (middle[0] + middle[1]) / 2
    late_center_x = (late[0] + late[1]) / 2

    assert late_width > early_width * 1.15
    assert middle_center_x > early_center_x + 5
    assert late_center_x > middle_center_x + 5
