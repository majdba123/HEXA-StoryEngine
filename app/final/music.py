"""Background music: a quiet, procedurally composed bed under the narration (2026-10-21).

Explainer practice: a music bed lifts retention as long as it never competes with the voice.
Here it sits ~15 dB under the speech level in pauses and ducks a further 8 dB under every
spoken word (side-chain from the narration itself), with a presence dip at 1.5-4 kHz so the
consonants stay clear.

Variety, so the viewer never gets used to one sound:

* six styles (ambient pad, tech pulse, investigation, light groove, cinematic build, warm
  keys), each with its own tempo range, key mode, instruments and chord progressions;
* the style, key, tempo and progressions are drawn from the package's own story (a stable
  seed), so different videos get different music and a re-render reproduces the same one;
* inside a video the arrangement changes at every character swap (Boundary scene whip): the
  intensity (which layers play) and the progression alternate, never the same twice in a row.

Composition is numpy only (no samples, no licensing), exactly the narration's length, faded in
and out. ``render`` raises on a broken input; ``app/final/sound.py`` mixes it and keeps the
effects (or the narration alone) when it fails, so music can never stop a render.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

import numpy as np

from app.final.synth import SAMPLE_RATE, adsr, band_noise, note_hz, partials, plan_seed
from app.models import RenderPlan

BACKGROUND_MUSIC = True
MUSIC_LEVEL = -15.0  # music RMS relative to the narration's speech RMS (dB), in pauses
DUCK_DB = 8.0  # further reduction while the voice speaks
DUCK_ATTACK, DUCK_RELEASE = 0.05, 0.45  # seconds
FADE_IN, FADE_OUT = 1.5, 2.5
# Chapters: a video this long changes style once, at the character swap nearest its middle
# (within CHAPTER_WINDOW of the duration), crossfading over CHAPTER_CROSSFADE seconds.
CHAPTER_MIN_SECONDS = 60.0
CHAPTER_WINDOW = (0.35, 0.65)
CHAPTER_CROSSFADE = 2.0

SCALES = {"minor": [0, 2, 3, 5, 7, 8, 10], "major": [0, 2, 4, 5, 7, 9, 11]}
PENTATONIC = {"minor": [0, 3, 5, 7, 10], "major": [0, 2, 4, 7, 9]}
# Chord roots as scale degrees (0 = tonic), four bars each.
PROGRESSIONS = {
    "minor": [[0, 5, 2, 6], [0, 3, 5, 4], [0, 6, 5, 6], [0, 5, 3, 4], [5, 3, 0, 6]],
    "major": [[0, 4, 5, 3], [0, 5, 3, 4], [5, 3, 0, 4], [0, 3, 5, 4], [3, 0, 4, 5]],
}
# style -> (modes, tempo range BPM)
STYLES: dict[str, tuple[tuple[str, ...], tuple[float, float]]] = {
    "ambient_pad": (("major", "minor"), (66.0, 74.0)),
    "tech_pulse": (("minor",), (100.0, 112.0)),
    "investigation": (("minor",), (80.0, 90.0)),
    "light_groove": (("major",), (88.0, 98.0)),
    "cinematic_build": (("minor",), (92.0, 100.0)),
    "warm_keys": (("major", "minor"), (76.0, 84.0)),
}


@dataclass(frozen=True, slots=True)
class MusicChoice:
    style: str
    mode: str
    tonic: int  # MIDI note of the bass tonic (A1..E2 range)
    tempo: float
    progressions: tuple[tuple[int, ...], tuple[int, ...]]
    seed: int
    sections: tuple[tuple[float, int], ...] = field(default=())  # (start seconds, intensity 0-2)
    second_style: str | None = None  # the second chapter's style (same key), from ``split``
    second_tempo: float = 0.0
    split: float | None = None

    def scale_hz(self, degree: int, octave: int = 0) -> float:
        scale = SCALES[self.mode]
        return note_hz(self.tonic + 12 * (octave + degree // 7) + scale[degree % 7])

    def pentatonic_hz(self, index: int, octave: int) -> float:
        penta = PENTATONIC[self.mode]
        return note_hz(self.tonic + 12 * (octave + index // 5) + penta[index % 5])


def story_seed(plan: RenderPlan) -> int:
    return plan_seed(*(f"{beat.id}:{beat.narration}" for beat in plan.story), f"{plan.duration:.2f}")


def choose(plan: RenderPlan) -> MusicChoice:
    """The music of a plan: style, key, tempo and per-section arrangement (deterministic)."""
    seed = story_seed(plan)
    rng = np.random.default_rng(seed)
    style = sorted(STYLES)[int(rng.integers(len(STYLES)))]
    modes, (slow, fast) = STYLES[style]
    mode = modes[int(rng.integers(len(modes)))]
    tonic = int(rng.integers(33, 41))  # A1 .. E2
    tempo = round(float(rng.uniform(slow, fast)), 1)
    first, second = rng.choice(len(PROGRESSIONS[mode]), size=2, replace=False)
    progressions = (tuple(PROGRESSIONS[mode][first]), tuple(PROGRESSIONS[mode][second]))
    # Sections: the arrangement changes at each character swap (scene whip), snapped to a bar.
    bar = 240.0 / tempo
    swaps = sorted(
        min(float(spec["start"]) for spec in (row.overlap_exits or {}).values())
        for row in plan.scene_boundaries
        if (row.audit or {}).get("hero_exit") == "scene_whip" and row.overlap_exits)
    starts = [0.0]
    for time in swaps:
        snapped = round(time / bar) * bar
        if snapped - starts[-1] >= 2 * bar and snapped < plan.duration - 2 * bar:
            starts.append(snapped)
    if len(starts) == 1:  # no swap: still change the arrangement every ~8 bars
        starts += [8 * bar * k for k in range(1, int(plan.duration // (8 * bar)) + 1)
                   if 8 * bar * k < plan.duration - 2 * bar]
    intensities = [1]  # the opening is light, never empty
    for _ in starts[1:]:
        options = [level for level in (0, 1, 2) if level != intensities[-1]]
        intensities.append(int(rng.choice(options, p=[0.35, 0.65] if 0 in options else [0.5, 0.5])))
    second_style, second_tempo, split = None, 0.0, None
    if plan.duration >= CHAPTER_MIN_SECONDS:
        others = [name for name in sorted(STYLES) if name != style]
        second_style = others[int(rng.integers(len(others)))]
        second_tempo = round(float(rng.uniform(*STYLES[second_style][1])), 1)
        low, high = (plan.duration * edge for edge in CHAPTER_WINDOW)
        middle = [time for time in swaps if low <= time <= high]
        split = round(min(middle, key=lambda time: abs(time - plan.duration / 2)) if middle
                      else round(plan.duration / 2 / bar) * bar, 3)
    return MusicChoice(style=style, mode=mode, tonic=tonic, tempo=tempo, progressions=progressions,
                       seed=seed, sections=tuple(zip(starts, intensities)), second_style=second_style,
                       second_tempo=second_tempo, split=split)


# -- instruments (mono unless noted) ------------------------------------------------------
def _time(seconds: float) -> np.ndarray:
    return np.arange(max(1, int(seconds * SAMPLE_RATE))) / SAMPLE_RATE


def _pad(freqs: list[float], seconds: float) -> np.ndarray:
    """Soft detuned pad (stereo: one detune per side), slow attack, long release. Its partials
    stay under 3 kHz, so it is drawn at half rate and interpolated up (images above 21 kHz)."""
    n = max(1, int(seconds * SAMPLE_RATE))
    half = n // 2 + 2
    t = np.arange(half, dtype=np.float32) * np.float32(2.0 / SAMPLE_RATE)
    low = np.zeros((half, 2), dtype=np.float32)
    for side, cents in ((0, -4.0), (1, 4.0)):
        for freq in freqs:
            f = freq * 2 ** (cents / 1200)
            low[:, side] += partials(t, f, [1, 2, 3, 4], [1, 0.28, 0.12, 0.05], [0] * 4, phase=side * 1.3)
    grid = np.arange(n) / 2.0
    out = np.stack([np.interp(grid, np.arange(half), low[:, side]) for side in (0, 1)], axis=1)
    return out * adsr(n, min(0.9, seconds / 3), min(1.2, seconds / 2.5))[:, None] / max(1, len(freqs))


def _pluck(freq: float, seconds: float, brightness: float = 1.0) -> np.ndarray:
    t = _time(seconds)
    ratios = [1, 2, 3, 4, 5, 6]
    body = partials(t, freq, ratios, [1 / k ** (1.6 - 0.4 * brightness) for k in ratios],
                    [0.42 / k for k in ratios])
    return body * adsr(len(t), 0.004, 0.03)


def _keys(freq: float, seconds: float) -> np.ndarray:
    t = _time(seconds)
    body = partials(t, freq, [1, 2, 3, 4], [1, 0.32, 0.1, 0.04], [1.3, 0.55, 0.3, 0.2])
    return body * adsr(len(t), 0.003, 0.08)


def _bell(freq: float, seconds: float = 2.2) -> np.ndarray:
    t = _time(seconds)
    return partials(t, freq, [1, 2.76, 5.4, 8.93], [1, 0.38, 0.16, 0.06], [1.5, 0.6, 0.28, 0.14]) * adsr(len(t), 0.002, 0.2)


def _bass(freq: float, seconds: float) -> np.ndarray:
    t = _time(seconds)
    return partials(t, freq, [1, 2, 3], [1, 0.25, 0.07], [2.5, 1.2, 0.6]) * adsr(len(t), 0.01, 0.08)


def _kick(rng: np.random.Generator) -> np.ndarray:
    t = _time(0.22)
    freq = 48 + 70 * np.exp(-t / 0.03)
    body = np.sin(2 * np.pi * np.cumsum(freq) / SAMPLE_RATE) * np.exp(-t / 0.09)
    return body * adsr(len(t), 0.002, 0.03)


def _noise_hit(rng: np.random.Generator, seconds: float, low: float, high: float, decay: float) -> np.ndarray:
    n = max(16, int(seconds * SAMPLE_RATE))
    t = np.arange(n) / SAMPLE_RATE
    hit = band_noise(n, rng, np.full(4, low), np.full(4, high)) * np.exp(-t / decay)
    peak = float(np.max(np.abs(hit))) or 1.0
    return hit / peak * adsr(n, 0.002, 0.01)


def _drone(freq: float, seconds: float, rng: np.random.Generator) -> np.ndarray:
    t = _time(seconds)
    swell = 0.75 + 0.25 * np.sin(2 * np.pi * 0.11 * t + rng.uniform(0, np.pi))
    tone = partials(t, freq, [1, 1.5, 2, 3], [1, 0.45, 0.3, 0.08], [0] * 4)
    air = band_noise(len(t), rng, np.full(4, 180.0), np.full(4, 700.0))
    air /= float(np.max(np.abs(air))) or 1.0
    out = (tone * swell + 0.18 * air) * adsr(len(t), min(1.5, seconds / 3), min(1.5, seconds / 3))
    return np.stack([out, np.roll(out, 240)], axis=1)


def _boom(freq: float, rng: np.random.Generator) -> np.ndarray:
    t = _time(1.6)
    body = partials(t, freq, [1, 2.0, 2.9], [1, 0.3, 0.1], [0.55, 0.3, 0.2])
    air = _noise_hit(rng, 1.6, 80.0, 500.0, 0.25) * 0.4
    return (body + air) * adsr(len(t), 0.006, 0.4)


# -- composition --------------------------------------------------------------------------
class _Score:
    def __init__(self, n: int) -> None:
        self.out = np.zeros((n, 2), dtype=np.float32)

    def add(self, time: float, sound: np.ndarray, gain: float, pan: float = 0.0) -> None:
        start = int(round(time * SAMPLE_RATE))
        if start >= len(self.out) or start < 0:
            return
        sound = sound[: len(self.out) - start]
        if sound.ndim == 1:
            left, right = np.cos((pan + 1) * np.pi / 4), np.sin((pan + 1) * np.pi / 4)
            self.out[start:start + len(sound), 0] += (sound * gain * left * 1.4142).astype(np.float32)
            self.out[start:start + len(sound), 1] += (sound * gain * right * 1.4142).astype(np.float32)
        else:
            self.out[start:start + len(sound)] += (sound * gain).astype(np.float32)


def compose(choice: MusicChoice, seconds: float) -> np.ndarray:
    """Stereo music of ``seconds`` (unlevelled, peak ~1): one style, or two chapters with an
    equal-power crossfade at ``choice.split``."""
    n = int(round(seconds * SAMPLE_RATE))
    if choice.second_style is None or choice.split is None or not 0 < choice.split < seconds:
        return _compose(choice, seconds, 0.0, seconds, choice.seed ^ 0x5EED)
    half = CHAPTER_CROSSFADE / 2
    first = _compose(choice, seconds, 0.0, choice.split + half, choice.seed ^ 0x5EED)
    second = _compose(replace(choice, style=choice.second_style, tempo=choice.second_tempo),
                      seconds, choice.split - half, seconds, choice.seed ^ 0xB0B)
    t = np.arange(n) / SAMPLE_RATE
    blend = np.clip((t - (choice.split - half)) / CHAPTER_CROSSFADE, 0.0, 1.0)[:, None]
    return first * np.cos(blend * np.pi / 2) + second * np.sin(blend * np.pi / 2)


def _compose(choice: MusicChoice, seconds: float, begin: float, end: float, seed: int) -> np.ndarray:
    """One style's stereo music over ``seconds``; only the bars sounding in [begin, end]."""
    n = int(round(seconds * SAMPLE_RATE))
    score = _Score(n)
    rng = np.random.default_rng(seed)
    beat = 60.0 / choice.tempo
    bar = 4 * beat
    sections = list(choice.sections) or [(0.0, 1)]

    def section_of(time: float) -> tuple[int, int]:
        index = max(k for k, (start, _) in enumerate(sections) if start <= time + 1e-6)
        return index, sections[index][1]

    for number in range(int(np.ceil(seconds / bar)) + 1):
        t0 = number * bar
        if t0 >= min(seconds, end):
            break
        if t0 + bar + 2.0 < begin:  # this bar's tails end before the span
            continue
        index, level = section_of(t0)
        progression = choice.progressions[index % 2]
        degree = progression[number % len(progression)]
        root = choice.scale_hz(degree, 0)  # bass register
        triad = [choice.scale_hz(degree + step, 2) for step in (0, 2, 4)]
        fifth = choice.scale_hz(degree + 4, 0)
        style = choice.style
        first_bar = index > 0 and (number == 0 or section_of(t0 - bar)[0] != index)
        if first_bar and style in {"cinematic_build", "investigation"}:
            score.add(t0, _boom(root, rng), 0.55)
        if style == "ambient_pad":
            score.add(t0, _pad(triad, bar + 1.2), 0.55)
            if level >= 1:
                for _ in range(1 + level):
                    slot = int(rng.integers(0, 8))
                    score.add(t0 + slot * beat / 2, _bell(choice.pentatonic_hz(int(rng.integers(0, 8)), 3)),
                              0.16, pan=float(rng.uniform(-0.5, 0.5)))
            if level >= 2:
                score.add(t0, _bass(root, bar), 0.35)
        elif style == "tech_pulse":
            score.add(t0, _pad(triad, bar + 1.0), 0.28)
            step = beat / 2 if level >= 1 else beat
            notes = [root * 2, fifth * 2, root * 4, fifth * 2]
            for k in range(int(round(bar / step))):
                score.add(t0 + k * step, _pluck(notes[k % len(notes)], min(0.35, step * 1.4), 0.6), 0.22,
                          pan=0.25 if k % 2 else -0.25)
            if level >= 1:
                score.add(t0, _bass(root, 2 * beat), 0.4)
                score.add(t0 + 2 * beat, _bass(root, 2 * beat), 0.35)
            if level >= 2:
                for k in range(8):
                    score.add(t0 + (k + 0.5) * beat / 2, _noise_hit(rng, 0.04, 6000, 12000, 0.012), 0.05, pan=0.4)
        elif style == "investigation":
            score.add(t0, _drone(root, bar + 1.5, rng), 0.32)
            for _ in range(1 + level):
                slot = int(rng.integers(0, 8))
                score.add(t0 + slot * beat / 2, _keys(choice.pentatonic_hz(int(rng.integers(0, 6)), 2), 1.6), 0.22,
                          pan=float(rng.uniform(-0.4, 0.4)))
            if level >= 1:
                for k in range(4):
                    score.add(t0 + k * beat, _noise_hit(rng, 0.03, 3000, 7000, 0.006), 0.04 if k % 2 else 0.06, pan=-0.3)
            if level >= 2:
                score.add(t0, _pad(triad, bar + 1.0), 0.22)
        elif style == "light_groove":
            arpeggio = triad + [triad[1]]
            for k in range(8):
                score.add(t0 + k * beat / 2, _pluck(arpeggio[k % 4], 0.4, 1.0), 0.17, pan=-0.3 + 0.6 * (k % 4) / 3)
            score.add(t0, _bass(root, 1.5 * beat), 0.42)
            score.add(t0 + 2.5 * beat, _bass(fifth, 1.5 * beat), 0.32)
            if level >= 1:
                for k in (0, 2):
                    score.add(t0 + k * beat, _kick(rng), 0.32)
                for k in range(8):
                    score.add(t0 + k * beat / 2, _noise_hit(rng, 0.05, 5000, 10000, 0.016), 0.06 if k % 2 else 0.035, pan=0.35)
            if level >= 2:
                score.add(t0, _pad(triad, bar + 1.0), 0.2)
        elif style == "cinematic_build":
            score.add(t0, _pad(triad, bar + 1.2), 0.42)
            pattern = [1, 1, 1.5, 1, 2, 1, 1.5, 1]
            subdivision = 4 if level >= 2 else 2
            step = beat / subdivision
            if level >= 1:
                for k in range(4 * subdivision):
                    score.add(t0 + k * step, _pluck(root * 2 * pattern[k % 8], min(0.22, step * 1.6), 0.3), 0.2,
                              pan=0.2 if k % 2 else -0.2)
            if level >= 2:
                score.add(t0, _bass(root, bar), 0.35)
        elif style == "warm_keys":
            chord = [choice.scale_hz(degree + step, 2) for step in (0, 2, 4, 7)]
            hits = (0,) if level == 0 else ((1, 3) if level == 1 else (0, 1.5, 3))
            for hit in hits:
                for k, freq in enumerate(chord):
                    score.add(t0 + hit * beat + 0.012 * k, _keys(freq, 1.4), 0.13, pan=-0.3 + 0.2 * k)
            score.add(t0, _bass(root, 2.5 * beat), 0.4)
            if level >= 1:
                score.add(t0 + 3 * beat, _bass(choice.scale_hz(degree + 1, 0), beat), 0.25)
            if level >= 2:
                for k in range(8):
                    score.add(t0 + k * beat / 2, _noise_hit(rng, 0.05, 5000, 10000, 0.016), 0.045, pan=0.35)
    return score.out.astype(np.float64)


# -- levelling and ducking ----------------------------------------------------------------
def _fast_length(n: int) -> int:
    """Smallest 2^a 3^b 5^c >= n (an FFT of a length with large prime factors is slow)."""
    best = 1 << max(0, (n - 1).bit_length())
    p5 = 1
    while p5 < best:
        p35 = p5
        while p35 < best:
            p = p35
            while p < n:
                p *= 2
            best = min(best, p)
            p35 *= 3
        p5 *= 5
    return best


def _eq(music: np.ndarray) -> np.ndarray:
    """Leave room for the voice: gentle 1.5-4 kHz presence dip and a soft top roll-off."""
    size = _fast_length(music.shape[0] + SAMPLE_RATE // 10)  # padding: no wrap-around ringing
    freqs = np.fft.rfftfreq(size, 1.0 / SAMPLE_RATE)
    dip = 1.0 - 0.45 * np.exp(-0.5 * ((np.log2(np.maximum(freqs, 1.0)) - np.log2(2500.0)) / 0.6) ** 2)
    gain = dip / (1.0 + (freqs / 9000.0) ** 2) * (freqs > 35.0)
    out = np.empty_like(music)
    for side in range(music.shape[1]):
        out[:, side] = np.fft.irfft(np.fft.rfft(music[:, side], n=size) * gain, n=size)[: music.shape[0]]
    return out


def duck_gain(voice: np.ndarray, speech_rms: float) -> np.ndarray:
    """Per-sample music gain: 1 in pauses, -DUCK_DB under speech (attack/release smoothed)."""
    hop = int(0.01 * SAMPLE_RATE)
    frames = len(voice) // hop + 1
    padded = np.zeros((frames * hop, voice.shape[1]))
    padded[: len(voice)] = voice
    rms = np.sqrt((padded.reshape(frames, hop, -1) ** 2).mean(axis=(1, 2)))
    target = np.where(rms > 0.25 * speech_rms, 10 ** (-DUCK_DB / 20), 1.0)
    smooth = np.empty(frames)
    level = 1.0
    down, up = 1 - np.exp(-0.01 / DUCK_ATTACK), 1 - np.exp(-0.01 / DUCK_RELEASE)
    for k in range(frames):
        level += (target[k] - level) * (down if target[k] < level else up)
        smooth[k] = level
    return np.interp(np.arange(len(voice)), np.arange(frames) * hop + hop / 2, smooth)


def render(plan: RenderPlan, voice: np.ndarray, speech_rms: float,
           choice: MusicChoice | None = None) -> tuple[np.ndarray, dict]:
    """Levelled, ducked stereo music of exactly ``len(voice)`` samples + its report."""
    choice = choice or choose(plan)
    seconds = len(voice) / SAMPLE_RATE
    music = _eq(compose(choice, seconds))[: len(voice)]
    if len(music) < len(voice):
        music = np.pad(music, ((0, len(voice) - len(music)), (0, 0)))
    body = music[int(FADE_IN * SAMPLE_RATE): max(int(FADE_IN * SAMPLE_RATE) + 1, len(music) - int(FADE_OUT * SAMPLE_RATE))]
    rms = float(np.sqrt((body ** 2).mean())) if body.size else 0.0
    if not np.isfinite(rms) or rms <= 1e-9:
        raise ValueError("composed music is silent")
    music *= speech_rms * 10 ** (MUSIC_LEVEL / 20) / rms
    fade = np.ones(len(music))
    a, r = min(len(music), int(FADE_IN * SAMPLE_RATE)), min(len(music), int(FADE_OUT * SAMPLE_RATE))
    fade[:a] = np.linspace(0.0, 1.0, a) ** 2
    if r:
        fade[len(music) - r:] *= np.linspace(1.0, 0.0, r) ** 1.5
    music *= (fade * duck_gain(voice, speech_rms))[:, None]
    report = {"style": choice.style, "key": f"{choice.tonic % 12}:{choice.mode}", "tempo": choice.tempo,
              "sections": [[round(start, 2), level] for start, level in choice.sections]}
    if choice.second_style and choice.split is not None:
        report["second_style"] = {"style": choice.second_style, "tempo": choice.second_tempo, "from": choice.split}
    return music, report
