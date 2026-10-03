from __future__ import annotations
# Owner-scoped Test2 coverage; historical regression content is preserved.

import json
import shutil
import subprocess
from subprocess import CompletedProcess
from pathlib import Path

import pytest
import numpy as np
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
from app.render.evidence import RenderedVisualEvidence as RenderedVisualQA
from app.final import FinalMediaVerifier
from app.render.renderer import FFmpegRenderer
import app.final.verification as final_verification


pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe required",
)


def test_final_media_probe_decodes_ffprobe_json_as_utf8(monkeypatch, tmp_path: Path) -> None:
    def fake_run(command, **kwargs):
        assert kwargs["encoding"] == "utf-8"
        return CompletedProcess(command, 0, stdout='{"format":{"tags":{"title":"هاكتيفست"}}}')

    monkeypatch.setattr(final_verification, "run_hidden", fake_run)
    probe = FinalMediaVerifier("ffprobe", "ffmpeg")._probe(tmp_path / "audio.mp3")
    assert probe["format"]["tags"]["title"] == "هاكتيفست"


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


def _decoded_rgb_frame(video: Path, timestamp: float) -> np.ndarray:
    result = subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", f"{timestamp:.3f}",
            "-i", str(video), "-frames:v", "1", "-vf", "scale=160:90",
            "-pix_fmt", "rgb24", "-f", "rawvideo", "pipe:1",
        ],
        check=True,
        capture_output=True,
    )
    frame = np.frombuffer(result.stdout, dtype=np.uint8)
    assert frame.size == 160 * 90 * 3
    return frame.reshape((90, 160, 3))


def test_release_render_smoke_produces_qa_clean_muxed_mp4(tmp_path: Path) -> None:
    """Exercise the real downstream release path with an actual encoded MP4.

    This intentionally crosses the boundaries that unit tests cannot prove together:
    RenderPlan -> FFmpegRenderer -> encoded H.264 -> FinalExporter audio mux ->
    FinalMediaVerifier technical proof -> RenderedVisualQA sampling.
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

    issues = FinalMediaVerifier("ffprobe", "ffmpeg").inspect(final, audio)
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
            "-count_frames",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            str(final),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(probe.stdout)
    streams = payload["streams"]
    stream_types = {stream["codec_type"] for stream in streams}
    assert {"video", "audio"}.issubset(stream_types)
    video_stream = next(stream for stream in streams if stream["codec_type"] == "video")
    audio_stream = next(stream for stream in streams if stream["codec_type"] == "audio")
    assert video_stream["r_frame_rate"] == "30/1"
    assert video_stream["avg_frame_rate"] == "30/1"
    assert 59 <= int(video_stream["nb_read_frames"]) <= 61
    video_duration = float(video_stream.get("duration") or payload["format"]["duration"])
    audio_duration = float(audio_stream.get("duration") or payload["format"]["duration"])
    assert abs(video_duration - plan.duration) <= 1.0 / plan.fps
    assert abs(video_duration - audio_duration) <= 0.10

    # Decode the encoded result rather than trusting Motion metadata. The reveal must
    # survive H.264 as measurable pixel activity in the authored object region.
    entry = _decoded_rgb_frame(final, 0.01)
    settled = _decoded_rgb_frame(final, 0.24)
    assert float(np.abs(entry.astype(np.int16) - settled.astype(np.int16)).mean()) > 1.0
