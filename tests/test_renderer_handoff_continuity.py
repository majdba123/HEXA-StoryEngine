from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import cv2
import numpy as np
import pytest
from PIL import Image, ImageDraw

from app.models import (
    CompositionBeat,
    LayoutItem,
    MotionCue,
    RenderPlan,
    StoryBeat,
    VisualAsset,
)
from app.recovery.detector import RecoveryDetector
from app.render.renderer import FFmpegRenderer


def _write_rgba_asset(path: Path, fill: tuple[int, int, int, int]) -> None:
    image = Image.new("RGBA", (220, 220), (255, 255, 255, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((12, 12, 208, 208), radius=24, fill=fill)
    image.save(path)


def _mean_white_distance(frame: np.ndarray) -> float:
    return float(np.mean(255.0 - frame.astype(np.float32)))


def _read_frames(path: Path) -> list[np.ndarray]:
    capture = cv2.VideoCapture(str(path))
    assert capture.isOpened(), f"failed to open {path}"
    frames: list[np.ndarray] = []
    while True:
        ok, frame = capture.read()
        if not ok:
            break
        frames.append(frame)
    capture.release()
    return frames


@pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg required",
)
def test_renderer_transition_has_no_outgoing_ghost_or_internal_white_flash(tmp_path: Path) -> None:
    first_asset = tmp_path / "first.png"
    second_asset = tmp_path / "second.png"
    _write_rgba_asset(first_asset, (30, 60, 185, 255))
    _write_rgba_asset(second_asset, (220, 70, 65, 255))

    assets = [
        VisualAsset(
            id="asset-first",
            scene_id="scene-first",
            role="primary",
            image_path=first_asset,
            extraction_method="test",
        ),
        VisualAsset(
            id="asset-second",
            scene_id="scene-second",
            role="primary",
            image_path=second_asset,
            extraction_method="test",
        ),
    ]
    story = [
        StoryBeat(
            id="beat-first",
            scene_id="scene-first",
            start=0.0,
            end=0.7290909090909092,
            audio_start=0.0,
            audio_end=0.91,
            narration="first",
            primary_asset_ids=["asset-first"],
            action="INTRODUCE",
        ),
        StoryBeat(
            id="beat-second",
            scene_id="scene-second",
            start=0.7290909090909092,
            end=2.0,
            audio_start=0.91,
            audio_end=2.0,
            narration="second",
            primary_asset_ids=["asset-second"],
            action="HANDOFF",
            handoff_from="beat-first",
        ),
    ]
    composition = [
        CompositionBeat(
            beat_id="beat-first",
            items=[LayoutItem(asset_id="asset-first", x=0.5, y=0.5, width=0.64, height=0.64)],
        ),
        CompositionBeat(
            beat_id="beat-second",
            items=[LayoutItem(asset_id="asset-second", x=0.5, y=0.5, width=0.64, height=0.64)],
        ),
    ]
    motion = [
        MotionCue(
            beat_id="beat-first",
            asset_id="asset-first",
            kind="reveal_in",
            start=0.0,
            end=0.16,
        ),
        MotionCue(
            beat_id="beat-second",
            asset_id="asset-second",
            kind="handoff_in",
            start=0.7290909090909092,
            end=0.8540909090909091,
        ),
    ]
    plan = RenderPlan(
        width=640,
        height=360,
        fps=30,
        duration=2.0,
        story=story,
        composition=composition,
        motion=motion,
        assets=assets,
    )

    output = tmp_path / "handoff.mp4"
    FFmpegRenderer("ffmpeg").render(plan, output)

    frames = _read_frames(output)
    assert len(frames) == 60
    # The second beat begins at encoded frame 22. From that frame onward the centre of
    # the scene must be dominated by the incoming red artwork, not a translucent blend
    # of the previous blue object. This catches the pale "ghost silhouette" regression.
    for frame_index in range(22, 28):
        center = frames[frame_index][180, 320]  # BGR
        assert int(center[2]) > int(center[0]) + 45, (frame_index, center.tolist())
        assert _mean_white_distance(frames[frame_index]) > 8.0, frame_index

    detector = RecoveryDetector("ffprobe", "ffmpeg")
    assert detector._white_flash_frames(output, duration=2.0) == []


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg required")
def test_white_flash_detector_rejects_real_internal_blank_frame(tmp_path: Path) -> None:
    frame_root = tmp_path / "frames"
    frame_root.mkdir()
    for frame_index in range(30):
        color = "white" if frame_index == 15 else "#203060"
        Image.new("RGB", (320, 180), color).save(frame_root / f"{frame_index:04d}.png")

    output = tmp_path / "internal-white.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-framerate",
            "30",
            "-i",
            str(frame_root / "%04d.png"),
            "-c:v",
            "libx264",
            "-crf",
            "12",
            "-pix_fmt",
            "yuv420p",
            "-bf",
            "0",
            str(output),
        ],
        check=True,
    )

    flashes = RecoveryDetector("ffprobe", "ffmpeg")._white_flash_frames(output, duration=1.0)
    assert any(entry["frame"] == 15 for entry in flashes), flashes



@pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg required",
)
def test_ordered_visual_unit_keeps_first_member_as_boundary_carrier(
    tmp_path: Path,
) -> None:
    previous_path = tmp_path / "previous.png"
    first_path = tmp_path / "ordered-first.png"
    second_path = tmp_path / "ordered-second.png"
    _write_rgba_asset(previous_path, (35, 70, 180, 255))
    _write_rgba_asset(first_path, (220, 55, 55, 255))
    _write_rgba_asset(second_path, (55, 180, 80, 255))

    assets = [
        VisualAsset(
            id="previous",
            scene_id="scene-1",
            role="primary",
            image_path=previous_path,
            extraction_method="test",
        ),
        VisualAsset(
            id="ordered-first",
            scene_id="scene-2",
            role="primary",
            image_path=first_path,
            extraction_method="test",
        ),
        VisualAsset(
            id="ordered-second",
            scene_id="scene-2",
            role="support",
            image_path=second_path,
            extraction_method="test",
        ),
    ]
    story = [
        StoryBeat(
            id="beat-1",
            scene_id="scene-1",
            start=0.0,
            end=0.8,
            audio_start=0.0,
            audio_end=0.8,
            narration="previous",
            primary_asset_ids=["previous"],
            action="INTRODUCE",
        ),
        StoryBeat(
            id="beat-2",
            scene_id="scene-2",
            start=0.8,
            end=1.8,
            audio_start=1.0,
            audio_end=1.7,
            narration="ordered",
            primary_asset_ids=["ordered-first"],
            support_asset_ids=["ordered-second"],
            action="HANDOFF",
            handoff_from="beat-1",
        ),
    ]
    composition = [
        CompositionBeat(
            beat_id="beat-1",
            items=[
                LayoutItem(
                    asset_id="previous",
                    x=0.5,
                    y=0.5,
                    width=0.62,
                    height=0.62,
                )
            ],
        ),
        CompositionBeat(
            beat_id="beat-2",
            items=[
                LayoutItem(
                    asset_id="ordered-first",
                    x=0.35,
                    y=0.5,
                    width=0.34,
                    height=0.50,
                    z=10,
                ),
                LayoutItem(
                    asset_id="ordered-second",
                    x=0.70,
                    y=0.5,
                    width=0.34,
                    height=0.50,
                    z=20,
                ),
            ],
        ),
    ]
    motion = [
        MotionCue(
            beat_id="beat-1",
            asset_id="previous",
            kind="reveal_in",
            start=0.0,
            end=0.18,
        ),
        MotionCue(
            beat_id="beat-2",
            asset_id="ordered-first",
            kind="reveal_in",
            start=1.0,
            end=1.22,
            params={
                "motion_order": {
                    "sequence_order": 1,
                    "internal_index": 0,
                    "internal_count": 2,
                    "stagger_applied": True,
                }
            },
        ),
        MotionCue(
            beat_id="beat-2",
            asset_id="ordered-second",
            kind="reveal_in",
            start=1.18,
            end=1.40,
            params={
                "motion_order": {
                    "sequence_order": 1,
                    "internal_index": 1,
                    "internal_count": 2,
                    "stagger_applied": True,
                }
            },
        ),
    ]
    plan = RenderPlan(
        width=640,
        height=360,
        fps=30,
        duration=1.8,
        story=story,
        composition=composition,
        motion=motion,
        assets=assets,
    )

    output = tmp_path / "ordered-carrier.mp4"
    FFmpegRenderer("ffmpeg").render(plan, output)

    frames = _read_frames(output)
    # beat-2 begins at encoded frame 24, while its first Motion cue intentionally
    # starts 0.20s later. The first ordered member must already cover the white canvas.
    boundary = frames[24]
    assert _mean_white_distance(boundary) > 5.0
    first_pixel = boundary[210, 224]  # BGR, first member at pre-motion offset.
    assert int(first_pixel[2]) > int(first_pixel[1]) + 50
    # The second member must still respect its own later reveal.
    second_pixel = boundary[210, 448]
    assert min(int(value) for value in second_pixel) > 235

    detector = RecoveryDetector("ffprobe", "ffmpeg")
    assert detector._white_flash_frames(output, duration=1.8) == []
