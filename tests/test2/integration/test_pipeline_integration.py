import shutil
# Owner-scoped Test2 coverage; historical regression content is preserved.
import struct
import wave
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from app.config import Settings
from app.pipeline import StoryEnginePipeline
from tests.support.unified_package import write_unified_package


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
    script = "First visual idea. Second visual result."
    first = "First visual idea."
    second = "Second visual result."
    second_start = script.index(second)
    package = write_unified_package(
        tmp_path / "package",
        script=script,
        package_id="integration-package",
        image_size=(640, 360),
        scenes=[
            {
                "scene_id": "s1", "order": 0,
                "script_span": {"text": first, "global_char_start": 0, "global_char_end": len(first)},
                "assets": [{
                    "asset_id": "a1", "role": "primary", "semantic_role": "OBJECT",
                    "script_text": first,
                    "script_span": {"text": first, "global_char_start": 0, "global_char_end": len(first)},
                    "appear_trigger": {"text": first, "global_char_start": 0, "global_char_end": len(first)},
                    "binding_type": "EXPLICIT", "visual_focus": "PRIMARY",
                    "visual_locator": {"coordinate_space": "normalized_scene", "cx": 0.5, "cy": 0.5, "width": 0.45, "height": 0.55},
                }],
            },
            {
                "scene_id": "s2", "order": 1,
                "script_span": {"text": second, "global_char_start": second_start, "global_char_end": second_start + len(second)},
                "assets": [{
                    "asset_id": "a2", "role": "result", "semantic_role": "RESULT",
                    "script_text": second,
                    "script_span": {"text": second, "global_char_start": second_start, "global_char_end": second_start + len(second)},
                    "appear_trigger": {"text": second, "global_char_start": second_start, "global_char_end": second_start + len(second)},
                    "binding_type": "EXPLICIT", "visual_focus": "RESULT",
                    "visual_locator": {"coordinate_space": "normalized_scene", "cx": 0.5, "cy": 0.5, "width": 0.45, "height": 0.55},
                }],
            },
        ],
    )
    for scene_id, shape in (("s1", "square"), ("s2", "circle")):
        scene_path = package / "images" / f"{scene_id}.png"
        image = Image.new("RGBA", (640, 360), "white")
        draw = ImageDraw.Draw(image)
        if shape == "square":
            draw.rounded_rectangle((176, 81, 464, 279), radius=28, fill=(40, 40, 40, 255))
        else:
            draw.ellipse((176, 81, 464, 279), fill=(225, 70, 70, 255))
        image.convert("RGB").save(scene_path)
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
