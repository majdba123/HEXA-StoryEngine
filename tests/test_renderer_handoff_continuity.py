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
