from __future__ import annotations

import shutil
from pathlib import Path

import cv2
import numpy as np
import pytest
from PIL import Image, ImageDraw

from app.models import CompositionBeat, LayoutItem, RenderPlan, StoryBeat, VisualAsset
from app.motion import MotionPlanner
from app.render.renderer import FFmpegRenderer


def _write_asset(path: Path) -> None:
    image = Image.new("RGBA", (180, 180), (255, 255, 255, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((12, 12, 168, 168), radius=24, fill=(220, 55, 55, 255))
    image.save(path)


def _red_centroid_x(frame: np.ndarray) -> float:
    blue, green, red = cv2.split(frame)
    mask = (red.astype(np.int16) - blue.astype(np.int16) > 70) & (
        red.astype(np.int16) - green.astype(np.int16) > 70
    )
    _, xs = np.where(mask)
    assert len(xs) > 20
    return float(xs.mean())


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg required")
def test_renderer_executes_motion_v3_program_and_settles_on_composition(tmp_path: Path) -> None:
    image_path = tmp_path / "asset.png"
    _write_asset(image_path)
    asset = VisualAsset(
        id="primary",
        scene_id="scene-001",
        role="primary",
        image_path=image_path,
        extraction_method="test",
    )
    beat = StoryBeat(
        id="beat-001",
        scene_id="scene-001",
        start=0.0,
        end=1.2,
        audio_start=0.24,
        audio_end=1.1,
        narration="explanation",
        primary_asset_ids=["primary"],
        action="INTRODUCE",
    )
    composition = [
        CompositionBeat(
            beat_id=beat.id,
            items=[
                LayoutItem(
                    asset_id="primary",
                    x=0.50,
                    y=0.50,
                    width=0.34,
                    height=0.58,
                    z=20,
                )
            ],
        )
    ]
    motion = MotionPlanner().plan([beat], composition)
    plan = RenderPlan(
        width=640,
        height=360,
        fps=30,
        duration=1.2,
        story=[beat],
        composition=composition,
        motion=motion,
        assets=[asset],
    )

    output = tmp_path / "motion-v3.mp4"
    FFmpegRenderer("ffmpeg").render(plan, output)

    capture = cv2.VideoCapture(str(output))
    assert capture.isOpened()
    frames: list[np.ndarray] = []
    while True:
        ok, frame = capture.read()
        if not ok:
            break
        frames.append(frame)
    capture.release()

    assert len(frames) == 36
    first_x = _red_centroid_x(frames[0])
    settled_x = _red_centroid_x(frames[20])
    assert abs(first_x - settled_x) > 8.0
    assert settled_x == pytest.approx(320.0, abs=12.0)


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg required")
def test_renderer_executes_choreography_scale_and_recoil(tmp_path: Path) -> None:
    from app.choreography import ChoreographyDirector
    from app.models import PackageModel, SceneSource

    image_path = tmp_path / "asset.png"
    support_path = tmp_path / "support.png"
    _write_asset(image_path)
    _write_asset(support_path)
    assets = [
        VisualAsset(id="primary", scene_id="scene-001", role="primary", image_path=image_path, extraction_method="test"),
        VisualAsset(id="support", scene_id="scene-001", role="support", image_path=support_path, extraction_method="test"),
    ]
    beat = StoryBeat(
        id="beat-001", scene_id="scene-001", start=0.0, end=1.6,
        audio_start=0.28, audio_end=1.45, narration="decline result",
        primary_asset_ids=["primary"], support_asset_ids=["support"], action="REVEAL_DETAIL",
    )
    package = PackageModel(
        root=tmp_path, package_id="p", scenes=[SceneSource(
            id="scene-001", image_path=image_path, order=1,
            units=[{"semantic_name":"subsequent_decline","narrative_function":"EXPLAIN_SUBSEQUENT_DECLINE"}],
        )], script="x",
    )
    composition = [CompositionBeat(beat_id=beat.id, items=[
        LayoutItem(asset_id="primary", x=0.32, y=0.50, width=0.30, height=0.50, z=20),
        LayoutItem(asset_id="support", x=0.72, y=0.50, width=0.25, height=0.42, z=15),
    ])]
    choreography = ChoreographyDirector().plan(package, [beat], assets)
    motion = MotionPlanner().plan([beat], composition, choreography)
    plan = RenderPlan(width=640, height=360, fps=30, duration=1.6, story=[beat], composition=composition, motion=motion, assets=assets)
    output = tmp_path / "choreo-motion.mp4"

    FFmpegRenderer("ffmpeg").render(plan, output)
    assert output.is_file() and output.stat().st_size > 0
    cap = cv2.VideoCapture(str(output))
    frames=[]
    while True:
        ok, frame=cap.read()
        if not ok: break
        frames.append(frame)
    cap.release()
    assert len(frames) == 48
