"""Retention review 2026-10-21: sound design, camera drift, opening hook, clarity rules.

Every feature is general (driven by the edit itself), never stops a render (a failure
falls back to the plain result and is recorded) and keeps narration timing exact.
"""
from __future__ import annotations

import shutil
import subprocess
import wave
from pathlib import Path

import numpy as np
import pytest

from app.final import sound
from app.models import (
    CompositionBeat,
    LayoutItem,
    MotionCue,
    RenderPlan,
    SceneBoundaryRelease,
    StoryBeat,
    TextCompositionBeat,
    TextLayoutItem,
    TextMotionCue,
)
from app.render import camera
from app.shared.narration import continues_idea, is_hook

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg required")


# -- narration rules ----------------------------------------------------------------------
@pytest.mark.parametrize(("text", "expected"), [
    ("وبعدين صار شي", True), ("بس هون المشكلة", True), ("لأنه بدو", True), ("لأنو بدو", True),
    ("يعني ببساطة", True), ("والهاكر هرب", True), ("وهون صار", True), ("فهيك بيصير", True),
    ("ولو كان", True), ("فالنتيجة", True), ("⁧بس⁩ هون", True),
    ("فقرر يهجم", False), ("الهاكر دخل", False), ("فلوس كتير", False), ("وزارة كبيرة", False),
    ("يعنيه", False), ("بسيطة", False), ("", False),
])
def test_a_sentence_continues_the_idea_only_after_a_connective(text, expected) -> None:
    assert continues_idea(text) is expected


@pytest.mark.parametrize(("text", "expected"), [
    ("تخيل إنك تتصفح موقع", True), ("ليش الهاكر بيعمل هيك؟", True), ("هل فكرت مرة", True),
    ("الهاكر دخل!", True), ("الهاكر دخل الموقع.", False), ("شوي شوي", False), ("كيفية العمل", False),
    ("الهاكر ذو القبعة السوداء.", False), ("", False),
])
def test_a_hook_is_a_question_an_exclamation_or_a_picture_this_opener(text, expected) -> None:
    assert is_hook(text) is expected


# -- sound ------------------------------------------------------------------------------
def _plan(duration: float = 6.0) -> RenderPlan:
    beats = [StoryBeat(id="b1", scene_id="s1", start=0.0, end=3.0, audio_start=0.2, audio_end=2.8,
                       narration="أول فكرة.", primary_asset_ids=["a"], support_asset_ids=[], action="REVEAL"),
             StoryBeat(id="b2", scene_id="s2", start=3.0, end=duration, audio_start=3.1, audio_end=5.8,
                       narration="فكرة تانية.", primary_asset_ids=["b"], support_asset_ids=[], action="REVEAL")]
    motion = [MotionCue(beat_id="b1", asset_id="a", kind="program_v3", start=0.4, end=0.8),
              MotionCue(beat_id="b2", asset_id="b", kind="program_v3", start=3.2, end=3.6,
                        params={"focus_wash": {"start": 4.5, "ramp": 0.2}})]
    boundary = SceneBoundaryRelease(
        beat_id="b2", from_beat_id="b1", mode="HARD_CUT", reason="test",
        overlap_exits={"a": {"start": 3.1, "end": 3.3, "direction": -1.0, "axis": 0.0, "fade": 0.0}},
        audit={"hero_exit": "scene_whip"})
    text = [TextMotionCue(beat_id="b1", text_cue_id="t1", kind="text", start=1.0, end=1.4),
            TextMotionCue(beat_id="b1", text_cue_id="t2", kind="text", start=0.5, end=0.9)]
    text_composition = [TextCompositionBeat(beat_id="b1", items=[
        TextLayoutItem(text_cue_id="t1", x=0.5, y=0.2, max_width=0.3, font_scale=1.35),
        TextLayoutItem(text_cue_id="t2", x=0.5, y=0.8, max_width=0.3, font_scale=0.8)])]
    return RenderPlan(duration=duration, story=beats, composition=[
        CompositionBeat(beat_id="b1", items=[LayoutItem(asset_id="a", x=0.5, y=0.5, width=0.3, height=0.3)]),
        CompositionBeat(beat_id="b2", items=[LayoutItem(asset_id="b", x=0.5, y=0.5, width=0.3, height=0.3)])],
        motion=motion, assets=[], scene_boundaries=[boundary], text_motion=text, text_composition=text_composition)


def test_effects_follow_the_edit_sparsely_with_priorities() -> None:
    events = sound.plan_events(_plan())
    kinds = [(event.kind, round(event.time, 2)) for event in events]
    assert ("whoosh", 3.1) in kinds and ("swell", 4.5) in kinds and ("pop", 0.4) in kinds
    assert ("tick", 1.0) in kinds                       # a large keyword ticks ...
    assert not any(kind == "tick" and t == 0.5 for kind, t in kinds)  # ... a small one, too close to the pop, never
    assert not any(kind == "pop" and t == 3.2 for kind, t in kinds)   # the whoosh owns the scene change
    times = sorted(event.time for event in events)
    assert all(b - a >= sound.MIN_GAP - 1e-9 for a, b in zip(times, times[1:]))
    assert next(event for event in events if event.kind == "whoosh").pan < 0  # travels left


@pytest.mark.parametrize("kind", ["whoosh", "swish", "pop", "tick", "swell"])
def test_each_effect_is_clean_normalised_and_never_ends_abruptly(kind) -> None:
    signal = sound.synthesize(kind)
    assert np.isfinite(signal).all() and np.max(np.abs(signal)) == pytest.approx(1.0)
    assert np.max(np.abs(signal[-20:])) < 0.05
    assert np.array_equal(signal, sound.synthesize(kind))  # deterministic


def _tone(path: Path, seconds: float) -> Path:
    t = np.arange(int(seconds * sound.SAMPLE_RATE)) / sound.SAMPLE_RATE
    voice = (0.2 * np.sin(2 * np.pi * 220 * t) * (np.sin(2 * np.pi * 2 * t) > 0)).astype(np.float64)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(sound.SAMPLE_RATE)
        handle.writeframes((np.repeat(voice[:, None], 2, axis=1) * 32767).astype("<i2").tobytes())
    return path


@needs_ffmpeg
def test_the_mix_keeps_the_narration_length_and_sits_under_the_voice(tmp_path: Path) -> None:
    narration = _tone(tmp_path / "voice.wav", 6.0)
    output, report = sound.mix_or_narration(_plan(), narration, tmp_path / "mix.wav")
    assert output == tmp_path / "mix.wav" and report["sound_effects"] == "mixed" and report["events"] >= 4
    with wave.open(str(output)) as mixed, wave.open(str(narration)) as voice:
        assert mixed.getnframes() == voice.getnframes()  # exact length: A/V timing unchanged
    voice_audio = sound._read_audio(narration, "ffmpeg")
    mixed_audio = sound._read_audio(output, "ffmpeg")
    bed = mixed_audio - voice_audio
    assert np.max(np.abs(mixed_audio)) < 1.0
    assert 0 < np.max(np.abs(bed)) < np.max(np.abs(voice_audio))  # effects under the voice


@needs_ffmpeg
def test_a_sound_failure_falls_back_to_the_narration(tmp_path: Path) -> None:
    missing = tmp_path / "missing.wav"
    output, report = sound.mix_or_narration(_plan(), missing, tmp_path / "mix.wav")
    assert output == missing and report["sound_effects"] == "skipped" and report["error"]


def test_effects_switch_off_returns_the_narration(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(sound, "SOUND_EFFECTS", False)
    narration = tmp_path / "voice.wav"
    assert sound.mix_or_narration(_plan(), narration, tmp_path / "mix.wav") == (narration, {"sound_effects": "off"})


# -- camera -----------------------------------------------------------------------------
def test_the_camera_alternates_per_idea_and_never_jumps() -> None:
    plan = _plan()
    keys = camera.idea_keys(plan)
    assert [t for t, _ in keys] == [0.0, 3.0, 6.0]
    assert [z for _, z in keys] == [0.0, camera.CAMERA_AMPLITUDE, 0.0]
    from app.render.expression import compile_expression

    zoom = compile_expression(camera.zoom_expression(keys, 30).replace("(in/30)", "(t)"))
    values = [zoom(frame / 30) for frame in range(0, 181)]
    assert max(abs(b - a) for a, b in zip(values, values[1:])) < 0.0005  # continuous, eased
    assert values[0] == pytest.approx(0.0) and values[90] == pytest.approx(camera.CAMERA_AMPLITUDE)


def test_idea_boards_do_not_restart_the_camera() -> None:
    plan = _plan()
    plan.scene_boundaries[0] = plan.scene_boundaries[0].model_copy(update={"audit": {"hero_exit": "idea_board"}})
    assert [t for t, _ in camera.idea_keys(plan)] == [0.0, 6.0]


@needs_ffmpeg
def test_the_camera_keeps_frame_size_count_and_sharpness(tmp_path: Path) -> None:
    from app.render.renderer import FFmpegRenderer

    video = tmp_path / "in.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=1920x1080:r=30:d=6",
                    "-pix_fmt", "yuv420p", str(video)], check=True)
    renderer = FFmpegRenderer("ffmpeg")
    out, report = camera.apply_or_keep(_plan(), video, tmp_path / "cam.mp4", ffmpeg_bin="ffmpeg",
                                       filter_option=renderer._filter_complex_file_option(tmp_path))
    assert report["camera"] == "drift" and out == tmp_path / "cam.mp4"
    probe = subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-show_entries",
                            "stream=width,height,nb_read_frames", "-of", "csv=p=0", str(out)],
                           capture_output=True, text=True, check=True).stdout.strip()
    assert probe == "1920,1080,180"


def test_a_camera_failure_keeps_the_video(tmp_path: Path) -> None:
    video = tmp_path / "not-a-video.mp4"
    video.write_bytes(b"x")
    out, report = camera.apply_or_keep(_plan(), video, tmp_path / "cam.mp4", ffmpeg_bin="ffmpeg",
                                       filter_option="-filter_complex_script")
    assert out == video and report["camera"] == "skipped"
