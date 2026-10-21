"""Sound variety 2026-10-21: six variants per effect, rotation, restraint, and the music bed.

The viewer must never get used to one sound: every effect kind rotates through six designs
(never the same twice in a row), the music style/key/tempo follow the story (different videos
differ, a re-render is identical), a long video changes style once, and the arrangement changes
at every character swap. None of it may stop a render or move the narration.
"""
from __future__ import annotations

import shutil
import wave
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from app.final import music, sound
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

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg required")
RATE = sound.SAMPLE_RATE


def _long_plan(seconds: float = 80.0, *, beat: float = 2.0, text: str = "قصة") -> RenderPlan:
    """A dense synthetic edit: a picture every ``beat`` seconds, a clear (fade) between all of
    them, a character swap (whip) every 5th, a big keyword on each and a wash every 4th."""
    beats, motion, boundaries, composition, cues, layout = [], [], [], [], [], []
    count = int(seconds // beat)
    for k in range(count):
        start = k * beat
        beats.append(StoryBeat(id=f"b{k}", scene_id=f"s{k // 5}", start=start, end=start + beat,
                               audio_start=start + 0.1, audio_end=start + beat - 0.1,
                               narration=f"{text} {k}.", primary_asset_ids=[f"a{k}"], support_asset_ids=[],
                               action="REVEAL"))
        params = {"focus_wash": {"start": start + 1.2, "ramp": 0.2}} if k % 4 == 3 else {}
        motion.append(MotionCue(beat_id=f"b{k}", asset_id=f"a{k}", kind="program_v3", start=start + 0.05,
                                end=start + 0.4, params=params))
        composition.append(CompositionBeat(beat_id=f"b{k}", items=[
            LayoutItem(asset_id=f"a{k}", x=0.2 + 0.6 * (k % 2), y=0.5, width=0.3, height=0.3)]))
        cues.append(TextMotionCue(beat_id=f"b{k}", text_cue_id=f"t{k}", kind="text", start=start + 0.9,
                                  end=start + 1.2))
        layout.append(TextCompositionBeat(beat_id=f"b{k}", items=[
            TextLayoutItem(text_cue_id=f"t{k}", x=0.5, y=0.2, max_width=0.3, font_scale=1.2)]))
        if k:
            whip = k % 5 == 0
            boundaries.append(SceneBoundaryRelease(
                beat_id=f"b{k}", from_beat_id=f"b{k - 1}", mode="HARD_CUT", reason="test",
                overlap_exits={f"a{k - 1}": {"start": start - 0.15, "end": start + 0.1, "direction": 1.0,
                                             "axis": 0.0, "fade": 0.0}},
                audit={"hero_exit": "scene_whip" if whip else "scene_fade"}))
    return RenderPlan(duration=count * beat, story=beats, composition=composition, motion=motion, assets=[],
                      scene_boundaries=boundaries, text_motion=cues, text_composition=layout)


def _speech(seconds: float, level: float = 0.2) -> np.ndarray:
    """Stereo 'speech': 220 Hz bursts, 0.6 s on / 0.4 s off."""
    t = np.arange(int(seconds * RATE)) / RATE
    voice = level * np.sin(2 * np.pi * 220 * t) * ((t % 1.0) < 0.6)
    return np.repeat(voice[:, None], 2, axis=1)


def _write(path: Path, audio: np.ndarray) -> Path:
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(RATE)
        handle.writeframes((np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes())
    return path


# -- effect variants ----------------------------------------------------------------------
@pytest.mark.parametrize("kind", sorted(sound.DEFAULT_SECONDS))
@pytest.mark.parametrize("variant", range(sound.VARIANTS))
def test_every_variant_is_clean_normalised_deterministic_and_never_ends_abruptly(kind, variant) -> None:
    signal = sound.synthesize(kind, variant=variant, length=0.8 if kind == "swell" else None)
    assert np.isfinite(signal).all() and np.max(np.abs(signal)) == pytest.approx(1.0)
    assert np.max(np.abs(signal[-20:])) < 0.05
    assert abs(float(signal.mean())) < 0.1  # no DC offset
    assert np.array_equal(signal, sound.synthesize(kind, variant=variant, length=0.8 if kind == "swell" else None))


@pytest.mark.parametrize("kind", sorted(sound.DEFAULT_SECONDS))
def test_the_six_variants_of_a_kind_really_sound_different(kind) -> None:
    def spectrum(variant: int) -> np.ndarray:
        signal = sound.synthesize(kind, variant=variant, length=0.8 if kind == "swell" else None)
        magnitude = np.abs(np.fft.rfft(signal, n=1 << 15))
        return magnitude / np.linalg.norm(magnitude)

    spectra = [spectrum(variant) for variant in range(sound.VARIANTS)]
    for a in range(sound.VARIANTS):
        for b in range(a + 1, sound.VARIANTS):
            assert float(spectra[a] @ spectra[b]) < 0.97, (kind, a, b)


def test_tonal_variants_follow_the_key() -> None:
    low, high = (sound.synthesize("pop", variant=4, tonic=hz) for hz in (330.0, 440.0))
    peak = [np.argmax(np.abs(np.fft.rfft(row, n=1 << 16))) * RATE / (1 << 16) for row in (low, high)]
    assert peak[0] == pytest.approx(330.0, rel=0.02) and peak[1] == pytest.approx(440.0, rel=0.02)


def test_the_rotation_plays_every_variant_before_repeating_and_never_twice_in_a_row() -> None:
    def sequence(seed: int) -> list[int]:
        rotation = sound.Rotation(seed=seed)
        return [rotation.next("pop") for _ in range(60)]

    played = sequence(123)
    assert all(a != b for a, b in zip(played, played[1:]))
    for start in range(0, 60, sound.VARIANTS):
        assert sorted(played[start:start + sound.VARIANTS]) == list(range(sound.VARIANTS))
    assert played != sequence(124)  # seeded per story
    assert played == sequence(123)  # and reproducible


# -- restraint ----------------------------------------------------------------------------
def test_effects_stay_sparse_one_per_transition_and_spaced_per_kind() -> None:
    plan = _long_plan()
    events = sound.plan_events(plan)
    times = [event.time for event in events]
    for start in times:
        assert sum(1 for time in times if start <= time < start + sound.WINDOW) <= sound.MAX_PER_WINDOW
    for kind, spacing in sound.KIND_SPACING.items():
        same = [event.time for event in events if event.kind == kind]
        assert all(b - a >= spacing - 1e-9 for a, b in zip(same, same[1:])), kind
    transitions = [event.time for event in events if event.kind in {"whoosh", "swish"}]
    for pop in (event.time for event in events if event.kind == "pop"):
        assert not any(0.0 <= pop - time <= sound.TRANSITION_COVERS for time in transitions)
    kinds = {event.kind for event in events}
    assert {"whoosh", "swish", "pop", "swell"} <= kinds
    assert sum(event.kind == "whoosh" for event in events) == sum(
        1 for row in plan.scene_boundaries if row.audit["hero_exit"] == "scene_whip")  # swaps always heard


def test_a_pop_pans_toward_where_its_picture_lands() -> None:
    pops = {round(event.time): event.pan for event in sound.plan_events(_long_plan()) if event.kind == "pop"}
    assert pops and all(-0.3 <= pan <= 0.3 for pan in pops.values())
    assert {np.sign(pan) for pan in pops.values()} == {-1.0, 1.0}


def test_the_effects_bed_rotates_variants_without_back_to_back_repeats() -> None:
    plan = _long_plan()
    bed, report = sound.effects_bed(plan, int(plan.duration * RATE), 0.1, music.choose(plan))
    assert bed.shape == (int(plan.duration * RATE), 2) and np.isfinite(bed).all()
    assert report["back_to_back_repeats"] == 0
    assert len(report["variants"]["pop"]) == sound.VARIANTS


# -- music --------------------------------------------------------------------------------
def test_music_follows_the_story_reproducibly_and_differs_between_videos() -> None:
    plan = _long_plan()
    assert music.choose(plan) == music.choose(plan)
    styles = {music.choose(_long_plan(text=f"قصة رقم {k}")).style for k in range(24)}
    assert len(styles) >= 4


def test_the_arrangement_changes_at_character_swaps_never_the_same_twice() -> None:
    choice = music.choose(_long_plan())
    starts = [start for start, _ in choice.sections]
    levels = [level for _, level in choice.sections]
    assert len(starts) >= 3 and starts[0] == 0.0 and levels[0] == 1
    assert all(a != b for a, b in zip(levels, levels[1:]))
    assert all(level in (0, 1, 2) for level in levels)


def test_a_long_video_changes_style_once_near_its_middle_and_a_short_one_keeps_one() -> None:
    plan = _long_plan(80.0)
    choice = music.choose(plan)
    assert choice.second_style and choice.second_style != choice.style
    assert music.CHAPTER_WINDOW[0] * plan.duration <= choice.split <= music.CHAPTER_WINDOW[1] * plan.duration
    short = music.choose(_long_plan(30.0))
    assert short.second_style is None and short.split is None


@pytest.mark.parametrize("style", sorted(music.STYLES))
def test_every_style_composes_clean_music(style) -> None:
    base = music.choose(_long_plan(30.0))
    choice = replace(base, style=style, mode=music.STYLES[style][0][0])
    score = music.compose(choice, 20.0)
    assert score.shape == (20 * RATE, 2) and np.isfinite(score).all()
    rms = float(np.sqrt((score ** 2).mean()))
    assert rms > 1e-3
    assert np.max(np.abs(np.diff(score, axis=0))) < 40 * rms  # no clicks


def test_the_music_is_exactly_the_narration_long_under_the_voice_and_ducks_under_speech() -> None:
    plan = _long_plan(30.0)
    voice = _speech(plan.duration)
    reference = sound._speech_rms(voice)
    score, report = music.render(plan, voice, reference)
    assert score.shape == voice.shape and np.isfinite(score).all()
    assert report["style"] in music.STYLES
    t = np.arange(len(voice)) / RATE
    body = (t > 3.0) & (t < plan.duration - 3.0)
    speaking = body & ((t % 1.0) > 0.1) & ((t % 1.0) < 0.55)
    pause = body & ((t % 1.0) > 0.9)
    rms = lambda mask: float(np.sqrt((score[mask] ** 2).mean()))  # noqa: E731
    assert rms(speaking) < reference * 10 ** (-18 / 20)  # well under the voice while it speaks
    assert 20 * np.log10(rms(pause) / rms(speaking)) > music.DUCK_DB * 0.5  # ducks under speech
    assert np.max(np.abs(score[: int(0.05 * RATE)])) < 0.01 * reference  # fades in
    assert np.max(np.abs(score[-int(0.05 * RATE):])) < 0.05 * reference  # fades out


@needs_ffmpeg
def test_the_full_mix_carries_effects_and_music_at_the_narration_length(tmp_path: Path) -> None:
    plan = _long_plan(30.0)
    narration = _write(tmp_path / "voice.wav", _speech(plan.duration))
    output, report = sound.mix_or_narration(plan, narration, tmp_path / "mix.wav")
    assert report["sound_effects"] == "mixed" and report["music"] == "mixed" and report["events"] >= 6
    with wave.open(str(output)) as mixed, wave.open(str(narration)) as voice:
        assert mixed.getnframes() == voice.getnframes()
    audio = sound._read_audio(output, "ffmpeg")
    assert np.max(np.abs(audio)) < 1.0


@needs_ffmpeg
def test_a_music_failure_keeps_the_effects_and_is_recorded(tmp_path: Path, monkeypatch) -> None:
    def broken(*args, **kwargs):
        raise RuntimeError("synth exploded")

    monkeypatch.setattr(music, "render", broken)
    plan = _long_plan(30.0)
    narration = _write(tmp_path / "voice.wav", _speech(plan.duration))
    output, report = sound.mix_or_narration(plan, narration, tmp_path / "mix.wav")
    assert output == tmp_path / "mix.wav"
    assert report["sound_effects"] == "mixed" and report["music"] == "skipped"
    assert "synth exploded" in report["music_error"] and report["events"] >= 6


@needs_ffmpeg
def test_music_switch_off_keeps_the_effects(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(music, "BACKGROUND_MUSIC", False)
    plan = _long_plan(30.0)
    narration = _write(tmp_path / "voice.wav", _speech(plan.duration))
    _, report = sound.mix_or_narration(plan, narration, tmp_path / "mix.wav")
    assert report["sound_effects"] == "mixed" and report["music"] == "off"


@needs_ffmpeg
def test_stems_hold_only_their_own_sound(tmp_path: Path) -> None:
    plan = _long_plan(30.0)
    narration = _write(tmp_path / "voice.wav", _speech(plan.duration))
    effects = sound.mix(plan, narration, tmp_path / "fx.wav", include_voice=False, stems=("effects",))
    bed = sound.mix(plan, narration, tmp_path / "music.wav", include_voice=False, stems=("music",))
    assert "music" not in effects and effects["events"] >= 6
    assert bed["music"] == "mixed" and "events" not in bed
    full = sound._read_audio(tmp_path / "fx.wav", "ffmpeg") + sound._read_audio(tmp_path / "music.wav", "ffmpeg")
    sound.mix(plan, narration, tmp_path / "both.wav", include_voice=False)
    assert np.max(np.abs(full - sound._read_audio(tmp_path / "both.wav", "ffmpeg"))) < 2e-3
