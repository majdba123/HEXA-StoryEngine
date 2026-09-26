from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from app.final import FinalExporter
from app.models import (
    CompositionBeat,
    LayoutItem,
    MotionCue,
    RenderPlan,
    StoryBeat,
    VisualAsset,
)
from app.qa import RenderedVisualQA
from app.recovery.detector import RecoveryDetector
from app.render.renderer import FFmpegRenderer


pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe required",
)


def _asset(path: Path, rgba: tuple[int, int, int, int]) -> None:
    image = Image.new("RGBA", (320, 240), (255, 255, 255, 0))
    block = Image.new("RGBA", (230, 170), rgba)
    image.alpha_composite(block, (45, 35))
    image.save(path)


def _make_audio(path: Path, duration: float) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=48000",
            "-t",
            f"{duration:.3f}",
            "-c:a",
            "pcm_s16le",
            str(path),
        ],
        check=True,
    )


def test_release_render_smoke_produces_qa_clean_muxed_mp4(tmp_path: Path) -> None:
    """Exercise the real downstream release path with an actual encoded MP4.

    This intentionally crosses the boundaries that unit tests cannot prove together:
    RenderPlan -> FFmpegRenderer -> encoded H.264 -> FinalExporter audio mux ->
    RecoveryDetector final-media QA -> RenderedVisualQA sampling.
    """
    first_path = tmp_path / "first.png"
    second_path = tmp_path / "second.png"
    _asset(first_path, (40, 90, 210, 255))
    _asset(second_path, (220, 70, 55, 255))

    assets = [
        VisualAsset(
            id="first",
            scene_id="scene-1",
            role="primary",
            image_path=first_path,
            extraction_method="smoke",
        ),
        VisualAsset(
            id="second",
            scene_id="scene-2",
            role="primary",
            image_path=second_path,
            extraction_method="smoke",
        ),
    ]
    story = [
        StoryBeat(
            id="beat-1",
            scene_id="scene-1",
            start=0.0,
            end=1.0,
            audio_start=0.0,
            audio_end=1.0,
            narration="first",
            primary_asset_ids=["first"],
            action="INTRODUCE",
        ),
        StoryBeat(
            id="beat-2",
            scene_id="scene-2",
            start=1.0,
            end=2.0,
            audio_start=1.0,
            audio_end=2.0,
            narration="second",
            primary_asset_ids=["second"],
            action="HANDOFF",
            handoff_from="beat-1",
        ),
    ]
    composition = [
        CompositionBeat(
            beat_id="beat-1",
            items=[
                LayoutItem(
                    asset_id="first",
                    x=0.50,
                    y=0.50,
                    width=0.70,
                    height=0.72,
                    z=10,
                )
            ],
        ),
        CompositionBeat(
            beat_id="beat-2",
            items=[
                LayoutItem(
                    asset_id="second",
                    x=0.50,
                    y=0.50,
                    width=0.70,
                    height=0.72,
                    z=10,
                )
            ],
        ),
    ]
    motion = [
        MotionCue(
            beat_id="beat-1",
            asset_id="first",
            kind="reveal_in",
            start=0.0,
            end=0.20,
        ),
        MotionCue(
            beat_id="beat-2",
            asset_id="second",
            kind="handoff_in",
            start=1.0,
            end=1.20,
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

    video_only = FFmpegRenderer("ffmpeg").render(
        plan,
        tmp_path / "video-only.mp4",
    )
    assert video_only.is_file()
    assert video_only.stat().st_size > 0

    audio = tmp_path / "narration.wav"
    _make_audio(audio, plan.duration)
    final = FinalExporter("ffmpeg").mux(
        video_only,
        audio,
        tmp_path / "final.mp4",
    )
    assert final.is_file()
    assert final.stat().st_size > 0

    issues = RecoveryDetector("ffprobe", "ffmpeg").inspect_final(final, audio)
    assert issues == [], [(issue.code, issue.context) for issue in issues]

    visual_report = RenderedVisualQA("ffmpeg").inspect(
        final,
        tmp_path / "diagnostics",
    )
    assert visual_report.sampled is True
    assert visual_report.contact_sheet is not None
    assert visual_report.contact_sheet.is_file()

    probe = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "stream=codec_type",
            "-of",
            "csv=p=0",
            str(final),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    stream_types = set(probe.stdout.split())
    assert {"video", "audio"}.issubset(stream_types)
