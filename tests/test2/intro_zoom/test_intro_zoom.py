from __future__ import annotations

import hashlib
import json
import math
import shutil
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
import numpy as np
from PIL import Image, ImageDraw

from app.desktop.job_process import GenerationJob, run_pipeline
from app.features.intro_zoom.assemble import _frame, _stream, prepend, probe
from app.features.intro_zoom.geometry import animated_crop, click_to_source, final_crop, fitted_rect
from app.features.intro_zoom.models import IntroZoomConfig
from app.features.intro_zoom.render import compose_frame, preview_frame, render_intro
from app.features.intro_zoom.validation import open_image, preflight, probe_voice
from app.shared.errors import GenerationCancelledError


def _ffmpeg(*args: str) -> None:
    result = subprocess.run(["ffmpeg", "-y", "-v", "error", *args],
                            capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr


@pytest.fixture
def image_file(tmp_path: Path) -> Path:
    image = Image.new("RGB", (1200, 700), "#24344f")
    draw = ImageDraw.Draw(image)
    for x, color in zip((160, 420, 680, 940, 280, 800),
                        ("red", "orange", "yellow", "cyan", "magenta", "lime")):
        y = 220 if x in (160, 420, 680, 940) else 500
        draw.ellipse((x - 80, y - 80, x + 80, y + 80), fill=color)
    path = tmp_path / "six-circles.png"
    image.save(path)
    return path


@pytest.fixture
def voice(tmp_path: Path) -> Path:
    path = tmp_path / "voice.wav"
    _ffmpeg("-f", "lavfi", "-i", "sine=frequency=440:duration=0.8:sample_rate=48000",
            "-c:a", "pcm_s16le", str(path))
    return path


@pytest.fixture
def original(tmp_path: Path) -> Path:
    path = tmp_path / "original.mp4"
    _ffmpeg("-f", "lavfi", "-i", "color=c=blue:s=320x180:r=30:d=1.2",
            "-f", "lavfi", "-i", "sine=frequency=880:duration=1.2:sample_rate=48000",
            "-frames:v", "36", "-c:v", "libx264", "-preset", "medium",
            "-profile:v", "high", "-level:v", "4.0", "-pix_fmt", "yuv420p",
            "-video_track_timescale", "15360", "-c:a", "aac", "-ar", "48000",
            "-ac", "2", "-b:a", "192k", str(path))
    return path


def test_config_and_letterboxed_click() -> None:
    area = fitted_rect(600, 600, 1200, 700)
    assert area.y == pytest.approx(125)
    assert click_to_source(300, 300, 600, 600, 1200, 700) == pytest.approx((0.5, 0.5))
    assert click_to_source(300, 124, 600, 600, 1200, 700) is None
    assert click_to_source(600, 300, 600, 600, 1200, 700) is None
    with pytest.raises(ValueError):
        IntroZoomConfig(Path("x"), Path("y"), math.nan, 0.5)
    with pytest.raises(ValueError):
        IntroZoomConfig(Path("x"), Path("y"), 0.5, 0.5, 8.1)


def test_complete_image_hold_and_zoom_preview_change(image_file: Path, voice: Path) -> None:
    source = open_image(image_file)
    near = final_crop(source.width, source.height, 320, 180, 0.5, 0.5, 1.25)
    far = final_crop(source.width, source.height, 320, 180, 0.5, 0.5, 4.0)
    assert far.width < near.width and far.height < near.height
    assert animated_crop(source.width, source.height, far, 0, 75).width == source.width
    assert animated_crop(source.width, source.height, far, 8, 75).width == source.width
    assert animated_crop(source.width, source.height, far, 74, 75) == far
    shallow = preflight(IntroZoomConfig(image_file, voice, 0.5, 0.5, 1.25))
    close = preflight(IntroZoomConfig(image_file, voice, 0.5, 0.5, 4.0))
    assert preview_frame(source, 320, 180, shallow, final=True).tobytes() != preview_frame(
        source, 320, 180, close, final=True).tobytes()


@pytest.mark.parametrize("focus", [(0, 0), (1, 0), (0, 1), (1, 1)])
def test_edge_target_has_no_empty_camera_frame(image_file: Path, voice: Path,
                                                focus: tuple[float, float]) -> None:
    source = open_image(image_file)
    config = IntroZoomConfig(image_file, voice, *focus)
    prepared = preflight(config)
    for width, height in ((320, 180), (180, 320)):
        crop = final_crop(source.width, source.height, width, height, *focus, 2.5)
        frame = compose_frame(source, width, height, crop)
        assert frame.size == (width, height)
        assert frame.getpixel((0, 0)) != (0, 0, 0)
        assert frame.getpixel((width - 1, height - 1)) != (0, 0, 0)
        preview = preview_frame(source, width, height, prepared, final=True)
        assert preview.size == (width, height)


def test_image_and_audio_validation(image_file: Path, voice: Path, tmp_path: Path) -> None:
    config = IntroZoomConfig(image_file, voice, 0.5, 0.5)
    prepared = preflight(config, workspace=tmp_path / "work")
    assert prepared.frames == 75
    assert prepared.duration == 2.5
    assert prepared.audio_duration == pytest.approx(0.8, abs=0.001)
    bad = tmp_path / "bad.png"
    bad.write_bytes(b"not an image")
    with pytest.raises(ValueError):
        open_image(bad)
    bad_audio = tmp_path / "bad.wav"
    bad_audio.write_bytes(b"not audio")
    with pytest.raises(ValueError):
        probe_voice(bad_audio)
    exact = tmp_path / "exact.wav"
    _ffmpeg("-f", "lavfi", "-i", "sine=frequency=440:duration=3:sample_rate=48000",
            "-c:a", "pcm_s16le", str(exact))
    assert preflight(IntroZoomConfig(image_file, exact, 0.5, 0.5)).frames == 90
    long = tmp_path / "long.wav"
    _ffmpeg("-f", "lavfi", "-i", "sine=frequency=440:duration=3.1:sample_rate=48000",
            "-c:a", "pcm_s16le", str(long))
    with pytest.raises(ValueError, match="3 seconds"):
        probe_voice(long)
    rotated = tmp_path / "rotated.jpg"
    portrait = Image.new("RGB", (50, 100), "red")
    metadata = Image.Exif()
    metadata[274] = 6
    portrait.save(rotated, exif=metadata)
    assert open_image(rotated).size == (100, 50)


def test_selector_rejects_padding_on_high_dpi_logical_coordinates(image_file: Path,
                                                                   monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    from app.features.intro_zoom.ui import ImageSelector

    app = QApplication.instance() or QApplication([])
    selector = ImageSelector()
    selector.resize(600, 600)
    selector.set_source(open_image(image_file))
    QTest.mouseClick(selector, Qt.MouseButton.LeftButton, pos=QPoint(300, 10))
    assert selector.focus is None
    QTest.mouseClick(selector, Qt.MouseButton.LeftButton, pos=QPoint(300, 300))
    assert selector.focus == pytest.approx((0.5, 0.5))
    selector.close()
    assert app is not None


def test_disabled_job_does_not_pass_intro_or_leak(monkeypatch: pytest.MonkeyPatch) -> None:
    from app import pipeline

    calls = []

    class FakePipeline:
        def __init__(self, settings):
            pass

        def generate_bundle(self, **kwargs):
            calls.append(kwargs)
            return kwargs

    monkeypatch.setattr(pipeline, "StoryEnginePipeline", FakePipeline)
    ordinary = GenerationJob(object(), Path("package.zip"), Path("audio.wav"), "ordinary")
    run_pipeline(ordinary, lambda *args: None, lambda: False)
    assert "intro_zoom" not in calls[0]
    config = IntroZoomConfig(Path("image.png"), Path("voice.wav"), 0.5, 0.5)
    selected = GenerationJob(object(), Path("package.zip"), Path("audio.wav"),
                             "selected", config)
    run_pipeline(selected, lambda *args: None, lambda: False)
    assert calls[1]["intro_zoom"] == config
    run_pipeline(ordinary, lambda *args: None, lambda: False)
    assert "intro_zoom" not in calls[2]


@pytest.mark.parametrize("focus", [(0.5, 0.5), (0.98, 0.02)])
def test_encoded_intro_join_and_cancellation(image_file: Path, voice: Path,
                                              original: Path, tmp_path: Path,
                                              focus: tuple[float, float]) -> None:
    prepared = preflight(IntroZoomConfig(image_file, voice, *focus))
    original_copy = tmp_path / f"original-{focus[0]}.mp4"
    shutil.copy2(original, original_copy)
    first_story_frame = _frame(original_copy, 0, "ffmpeg")
    intro = render_intro(prepared, 320, 180, tmp_path / f"intro-{focus[0]}.mp4",
                         level=40)
    info = probe(intro)
    assert int(_stream(info, "video")["nb_frames"]) == 75
    assert float(_stream(info, "audio")["duration"]) >= 2.48  # voice is padded
    outcome = prepend(intro, original_copy, prepared, tmp_path / "assemble")
    assert outcome["frames"] == 111
    assert _frame(original_copy, 75, "ffmpeg") == first_story_frame
    assert outcome["assembly"] in {"video_stream_copy", "video_reencode_fallback"}
    assert outcome["video_duration"] == pytest.approx(3.7, abs=1 / 30)
    def strongest_tone(start: float) -> float:
        samples = subprocess.run(
            ["ffmpeg", "-v", "error", "-ss", str(start), "-i", str(original_copy),
             "-map", "0:a:0", "-t", "0.20", "-ac", "1", "-ar", "48000",
             "-f", "s16le", "-"], capture_output=True, check=True).stdout
        wave = np.frombuffer(samples, dtype="<i2").astype(np.float32)
        spectrum = np.abs(np.fft.rfft(wave))
        return float(np.fft.rfftfreq(len(wave), 1 / 48000)[np.argmax(spectrum)])

    assert strongest_tone(0.2) == pytest.approx(440, abs=10)
    assert strongest_tone(2.55) == pytest.approx(880, abs=10)
    digest = hashlib.sha256(original_copy.read_bytes()).hexdigest()
    with pytest.raises(GenerationCancelledError):
        prepend(intro, original_copy, prepared, tmp_path / "cancelled", cancelled=lambda: True)
    assert hashlib.sha256(original_copy.read_bytes()).hexdigest() == digest
    assert not (tmp_path / "cancelled" / "candidate.mp4").exists()
    stopped = tmp_path / "stopped.mp4"
    with pytest.raises(GenerationCancelledError):
        render_intro(prepared, 320, 180, stopped, cancelled=lambda: True)
    assert not stopped.exists()


def test_incompatible_profile_uses_safe_fallback(image_file: Path, voice: Path,
                                                 original: Path, tmp_path: Path) -> None:
    prepared = preflight(IntroZoomConfig(image_file, voice, 0.5, 0.5))
    intro = render_intro(prepared, 320, 180, tmp_path / "intro.mp4", level=40)
    baseline = tmp_path / "baseline.mp4"
    _ffmpeg("-i", str(original), "-c:v", "libx264", "-preset", "ultrafast",
            "-profile:v", "baseline", "-pix_fmt", "yuv420p", "-c:a", "copy",
            str(baseline))
    outcome = prepend(intro, baseline, prepared, tmp_path / "fallback")
    assert outcome["assembly"] == "video_reencode_fallback"
    assert outcome["frames"] == 111
    assert _frame(baseline, 75, "ffmpeg")


def test_exactly_three_second_voice_is_preserved(image_file: Path, original: Path,
                                                 tmp_path: Path) -> None:
    voice = tmp_path / "three-seconds.wav"
    _ffmpeg("-f", "lavfi", "-i", "sine=frequency=440:duration=3:sample_rate=48000",
            "-c:a", "pcm_s16le", str(voice))
    prepared = preflight(IntroZoomConfig(image_file, voice, 0.5, 0.5))
    assert prepared.frames == 90 and prepared.duration == 3.0
    intro = render_intro(prepared, 320, 180, tmp_path / "intro-three.mp4", level=40)
    assert float(_stream(probe(intro), "audio")["duration"]) >= 3.0
    joined = tmp_path / "joined-three.mp4"
    shutil.copy2(original, joined)
    outcome = prepend(intro, joined, prepared, tmp_path / "join-three")
    assert outcome["frames"] == 126
    assert outcome["video_duration"] == pytest.approx(4.2, abs=1 / 30)


def test_transition_finishes_on_existing_first_frame(image_file: Path, voice: Path,
                                                    original: Path, tmp_path: Path) -> None:
    prepared = preflight(IntroZoomConfig(image_file, voice, 0.5, 0.5))
    first = Image.frombytes("RGB", (320, 180), _frame(original, 0, "ffmpeg"))
    intro = render_intro(prepared, 320, 180, tmp_path / "intro-transition.mp4",
                         level=40, next_frame=first)
    actual = np.frombuffer(_frame(intro, 74, "ffmpeg"), dtype=np.uint8).astype(np.int16)
    expected = np.frombuffer(first.tobytes(), dtype=np.uint8).astype(np.int16)
    assert np.mean(np.abs(actual - expected)) < 10


def test_versioned_pipeline_adapter_and_disabled_export_identity(
    image_file: Path, voice: Path, original: Path, tmp_path: Path,
) -> None:
    """Exercise the real reserve/render/intro/manifest/publish boundary with light media."""
    from app.final.bundle import ExportBundleWriter
    from app.final.verification import FinalMediaVerifier
    from app.pipeline import StoryEnginePipeline, TargetOutput, _PreparedTargets

    exports = tmp_path / "exports"
    exports.mkdir()
    work = tmp_path / "work"
    target = SimpleNamespace(target_id="SAMPLE", output_suffix="SAMPLE")
    pipeline = StoryEnginePipeline.__new__(StoryEnginePipeline)
    pipeline.settings = SimpleNamespace(
        work_root=work, ffmpeg_bin="ffmpeg", ffprobe_bin="ffprobe",
        render_resources=SimpleNamespace(keep_intermediates=False))
    pipeline.final_media = FinalMediaVerifier()

    def prepare(**kwargs):
        job_id = kwargs["job_id"] or "job"
        workspace = work / job_id
        workspace.mkdir(parents=True, exist_ok=True)
        return _PreparedTargets(
            job_id=job_id, workspace=workspace, audio_path=voice,
            started=time.perf_counter(), export_root=SimpleNamespace(root=exports),
            shared=SimpleNamespace(package=SimpleNamespace(
                project_slug="INTRO_SAMPLE", package_id="INTRO_SAMPLE")),
            plans={"SAMPLE": object()}, workspaces={"SAMPLE": workspace},
            plan_seconds={"SAMPLE": 0.0},
        )

    def render(shared, chosen, plan, workspace, output_file, audio_path, **kwargs):
        output_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(original, output_file)
        return TargetOutput(
            target_id="SAMPLE", path=output_file, width=320, height=180, fps=30,
            duration=1.2, frame_count=36, render_plan_path=workspace / "render-plan.json",
            render_plan_fingerprint="sample", encoded_motion_ok=True, final_media_ok=True,
            media=pipeline.final_media.summary(output_file), seconds=0, worker_count=1,
        )

    def manifest(**kwargs):
        output = kwargs["outputs"]["SAMPLE"]
        return {"completed": True, "outputs": {"SAMPLE": {
            "filename": output.path.name, "duration": output.duration,
            "frame_count": output.frame_count, "media": output.media,
        }}}

    pipeline._prepare_targets = prepare
    pipeline._render_target = render
    pipeline._manifest = manifest
    source_hash = hashlib.sha256(original.read_bytes()).hexdigest()
    first = pipeline.generate_bundle(package_path=tmp_path / "package.zip",
                                     audio_path=voice, job_id="no-intro-1", targets=(target,))
    assert hashlib.sha256(first.outputs["SAMPLE"].path.read_bytes()).hexdigest() == source_hash
    assert "intro_zoom" not in json.loads(first.manifest_path.read_text())
    assert ExportBundleWriter.is_complete(first.directory)

    chosen = IntroZoomConfig(image_file, voice, 0.5, 0.5)
    second = pipeline.generate_bundle(package_path=tmp_path / "package.zip",
                                      audio_path=voice, job_id="with-intro", targets=(target,),
                                      intro_zoom=chosen)
    manifest_data = json.loads(second.manifest_path.read_text())
    assert second.version == 2
    assert second.outputs["SAMPLE"].frame_count == 111
    assert manifest_data["intro_zoom"]["focus"] == [0.5, 0.5]
    assert manifest_data["intro_zoom"]["targets"]["SAMPLE"]["frames"] == 111
    assert ExportBundleWriter.is_complete(second.directory)

    third = pipeline.generate_bundle(package_path=tmp_path / "package.zip",
                                     audio_path=voice, job_id="no-intro-2", targets=(target,))
    assert third.version == 3
    assert hashlib.sha256(third.outputs["SAMPLE"].path.read_bytes()).hexdigest() == source_hash
    assert "intro_zoom" not in json.loads(third.manifest_path.read_text())
