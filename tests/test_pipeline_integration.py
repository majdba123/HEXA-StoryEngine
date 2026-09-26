import shutil
import struct
import wave
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from app.config import Settings
from app.pipeline import StoryEnginePipeline


def _write_wav(path: Path, seconds: float = 2.0, rate: int = 16000) -> None:
    frames = int(seconds * rate)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(b"".join(struct.pack("<h", 0) for _ in range(frames)))


def _write_asset(path: Path, shape: str) -> None:
    image = Image.new("RGBA", (260, 260), (255, 255, 255, 0))
    draw = ImageDraw.Draw(image)
    if shape == "square":
        draw.rounded_rectangle((30, 40, 230, 220), radius=28, fill=(40, 40, 40, 255))
    else:
        draw.ellipse((35, 35, 225, 225), fill=(225, 70, 70, 255))
    image.save(path)


@pytest.mark.skipif(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None, reason="ffmpeg required")
def test_pipeline_generates_final_video(tmp_path: Path) -> None:
    package = tmp_path / "package"
    package.mkdir()
    scene1 = package / "scene-1.png"
    scene2 = package / "scene-2.png"
    asset1 = package / "asset-1.png"
    asset2 = package / "asset-2.png"
    Image.new("RGB", (640, 360), "white").save(scene1)
    Image.new("RGB", (640, 360), "white").save(scene2)
    _write_asset(asset1, "square")
    _write_asset(asset2, "circle")
    (package / "script.txt").write_text("First visual idea. Second visual result.", encoding="utf-8")
    (package / "manifest.json").write_text(
        """{
          "package_id": "integration-package",
          "scenes": [
            {"id": "s1", "image": "scene-1.png"},
            {"id": "s2", "image": "scene-2.png"}
          ],
          "assets": [
            {"id": "a1", "scene_id": "s1", "role": "primary", "path": "asset-1.png"},
            {"id": "a2", "scene_id": "s2", "role": "result", "path": "asset-2.png"}
          ]
        }""",
        encoding="utf-8",
    )
    audio = tmp_path / "audio.wav"
    _write_wav(audio)

    settings = Settings(
        work_root=tmp_path / "work",
        output_root=tmp_path / "outputs",
        ffmpeg_bin="ffmpeg",
        ffprobe_bin="ffprobe",
        whisper_model="small",
        engine_host="127.0.0.1",
        engine_port=8765,
        allow_scene_fallback=False,
    )
    output = StoryEnginePipeline(settings).generate(
        package_path=package,
        audio_path=audio,
        job_id="integration-job",
    )

    assert output.is_file()
    assert output.stat().st_size > 0
    assert (
        tmp_path
        / "work"
        / "integration-job"
        / "preflight"
        / "ffmpeg-render-preflight.mp4"
    ).is_file()
    assert (
        tmp_path
        / "work"
        / "integration-job"
        / "preflight"
        / "ffmpeg-final-preflight.mp4"
    ).is_file()
    assert (tmp_path / "work" / "integration-job" / "render-plan.json").is_file()
