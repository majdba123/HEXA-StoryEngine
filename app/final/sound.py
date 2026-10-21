"""Sound design: motion-driven sound effects and a music bed under the narration (2026-10-21).

Retention review: the videos carried the narration alone. Explainer practice keeps the voice
on top, effects 8-16 dB below it and sparse (over-use turns busy fast). Every effect here is
driven by an event the edit already owns, so it lands on the exact frame of its motion:

* ``whoosh``  a character swap (Boundary scene whip), panned the way the scene travels;
* ``swish``   a clear between ideas (scene fade), softer and shorter;
* ``pop``     the first element of each new picture landing, panned to where it lands;
* ``tick``    a large keyword appearing (font scale >= 1.0), very quiet;
* ``swell``   the grey-wash climax of an idea (focus wash), a soft rise under its ramp.

Variety (the same sound every time gets old within a minute): every kind has six variants
that express the same moment differently. A shuffled rotation per kind plays every variant
before any repeats and never the same one twice in a row; each play also gets a small pitch
(+-5 %) and level (+-1.5 dB) humanisation. Tonal variants are tuned to the key of the music
bed (``app/final/music.py``) instead of being detuned. Everything is seeded from the story,
so a re-render is identical and different videos sound different.

Restraint: one sound per transition (a picture landing right after a whoosh/swish is already
heard), a minimum spacing per kind, and at most MAX_PER_WINDOW effects in any WINDOW seconds
(the highest priorities stay).

Effects are synthesized (numpy, deterministic, no licensing), levelled against the
narration's own speech level and summed with the music through a soft limiter. The mixed
track keeps the narration's exact length and sample rate, so A/V timing and every QA duration
check are unchanged. A failure never stops a render: the music failing keeps the effects,
anything else falls back to the narration alone, and the reason is recorded.
"""

from __future__ import annotations

import subprocess
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from app.final import music as music_bed
from app.final.synth import SAMPLE_RATE, band_noise as _band_noise, envelope as _envelope
from app.final.synth import partials, plan_seed, resample
from app.models import RenderPlan
from app.shared.process import run_hidden

SOUND_EFFECTS = True
MIN_GAP = 0.25  # seconds between two effects (restraint)
TICK_MIN_FONT_SCALE = 1.0
# Loudness (RMS while sounding) of each effect relative to the narration's speech RMS (dB):
# voice on top, effects 8-16 dB under it.
LEVELS = {"whoosh": -8.0, "swish": -12.0, "pop": -9.0, "tick": -16.0, "swell": -12.0}
# A tick is the lightest accent: it plays only with no other effect this close.
TICK_CLEARANCE = 0.6
PRIORITY = {"whoosh": 0, "swell": 1, "swish": 2, "pop": 3, "tick": 4}
# Same-kind spacing (seconds): a clear every couple of seconds turns into a metronome.
KIND_SPACING = {"swish": 3.0, "tick": 2.0, "swell": 2.0}
TRANSITION_COVERS = 0.8  # a pop this soon after a heard whoosh/swish belongs to that transition
WINDOW, MAX_PER_WINDOW = 10.0, 6
VARIANTS = 6
PITCH_JITTER = 0.05
LEVEL_JITTER_DB = 1.5
# Variants with a musical pitch: tuned to the music's key instead of jittered.
TONAL = frozenset({("pop", 4), ("pop", 5), ("tick", 2), ("swell", 0), ("swell", 2), ("swell", 4), ("swell", 5)})


@dataclass(frozen=True, slots=True)
class SoundEvent:
    kind: str
    time: float  # seconds; the instant the motion starts
    pan: float = 0.0  # -1 left .. 1 right
    length: float | None = None


def plan_events(plan: RenderPlan) -> list[SoundEvent]:
    """Effects of a final RenderPlan, sparse and on their motion's frame."""
    beats = {beat.id: beat for beat in plan.story}
    events: list[SoundEvent] = []
    for row in plan.scene_boundaries:
        kind = (row.audit or {}).get("hero_exit")
        specs = list((row.overlap_exits or {}).values())
        if not specs:
            continue
        start = min(float(spec["start"]) for spec in specs)
        if kind == "scene_whip":
            direction = float(specs[0].get("direction", 0.0))
            events.append(SoundEvent("whoosh", start, pan=-0.4 if direction < 0 else 0.4))
        elif kind == "scene_fade":
            events.append(SoundEvent("swish", start))
    positions = {(row.beat_id, item.asset_id): item.x for row in plan.composition for item in row.items}
    for beat_id, beat in beats.items():
        cues = [cue for cue in plan.motion if cue.beat_id == beat_id]
        if cues:
            first = min(cues, key=lambda cue: cue.start)
            pan = float(np.clip((positions.get((beat_id, first.asset_id), 0.5) - 0.5) * 0.6, -0.3, 0.3))
            events.append(SoundEvent("pop", max(float(beat.start), float(first.start)), pan=round(pan, 3)))
    scales = {item.text_cue_id: item.font_scale for row in plan.text_composition for item in row.items}
    for cue in plan.text_motion:
        if scales.get(cue.text_cue_id, 0.0) >= TICK_MIN_FONT_SCALE:
            events.append(SoundEvent("tick", float(cue.start)))
    for cue in plan.motion:
        wash = cue.params.get("focus_wash") if isinstance(cue.params, dict) else None
        if isinstance(wash, dict) and "start" in wash:
            events.append(SoundEvent("swell", float(wash["start"]), length=float(wash.get("ramp", 0.2)) + 0.6))
    chosen: list[SoundEvent] = []
    for event in sorted(events, key=lambda row: (PRIORITY[row.kind], row.time)):
        if _admits(chosen, event, plan.duration):
            chosen.append(event)
    return sorted(chosen, key=lambda row: row.time)


def _admits(chosen: list[SoundEvent], event: SoundEvent, duration: float) -> bool:
    if not 0.0 <= event.time < duration:
        return False
    gap = TICK_CLEARANCE if event.kind == "tick" else MIN_GAP
    if any(abs(event.time - other.time) < gap for other in chosen):
        return False
    spacing = KIND_SPACING.get(event.kind, 0.0)
    if spacing and any(other.kind == event.kind and abs(event.time - other.time) < spacing for other in chosen):
        return False
    if event.kind == "pop" and any(other.kind in {"whoosh", "swish"} and 0.0 <= event.time - other.time <= TRANSITION_COVERS
                                   for other in chosen):
        return False
    # Density: every WINDOW-second span holding this event keeps at most MAX_PER_WINDOW (a
    # span's count peaks when it starts on an event, so only those starts are checked).
    times = sorted([other.time for other in chosen] + [event.time])
    return all(sum(1 for time in times if start <= time < start + WINDOW) <= MAX_PER_WINDOW
               for start in times if start <= event.time < start + WINDOW)


class Rotation:
    """Per kind: every variant once (shuffled) before any repeats, never twice in a row."""

    def __init__(self, seed: int, variants: int = VARIANTS) -> None:
        self.rng = np.random.default_rng(seed)
        self.variants = variants
        self.bags: dict[str, list[int]] = {}
        self.last: dict[str, int] = {}

    def next(self, kind: str) -> int:
        bag = self.bags.get(kind)
        if not bag:
            bag = [int(value) for value in self.rng.permutation(self.variants)]
            if self.variants > 1 and bag[0] == self.last.get(kind):
                bag[0], bag[-1] = bag[-1], bag[0]
            self.bags[kind] = bag
        choice = bag.pop(0)
        self.last[kind] = choice
        return choice


# -- synthesis (numpy only) -------------------------------------------------------------------
def _sweep(n: int, rng: np.random.Generator, center: np.ndarray, width: tuple[float, float],
           attack: float, curve: float) -> np.ndarray:
    return _band_noise(n, rng, center * width[0], center * width[1]) * _envelope(n, attack, curve)


def _whoosh(variant: int, n: int, rng: np.random.Generator, steps: np.ndarray) -> np.ndarray:
    t = np.arange(n) / SAMPLE_RATE
    if variant == 0:  # air sweep
        return _sweep(n, rng, 500 + 2600 * np.sin(np.pi * steps) ** 1.5, (0.55, 1.6), 0.45, 2.0)
    if variant == 1:  # dark and wide
        return _sweep(n, rng, 350 + 1500 * np.sin(np.pi * steps), (0.4, 2.2), 0.5, 2.2)
    if variant == 2:  # bright and quick
        return _sweep(n, rng, 800 + 3400 * np.sin(np.pi * steps) ** 2, (0.6, 1.5), 0.4, 2.6)
    if variant == 3:  # doppler: air plus a faint tonal glide
        air = _sweep(n, rng, 600 + 2200 * np.sin(np.pi * steps) ** 1.5, (0.55, 1.6), 0.5, 2.0)
        glide = 220 + 300 * np.sin(np.pi * np.linspace(0, 1, n)) ** 2
        tone = np.sin(2 * np.pi * np.cumsum(glide) / SAMPLE_RATE) * _envelope(n, 0.5, 2.0)
        return air / (np.max(np.abs(air)) or 1.0) + 0.25 * tone
    if variant == 4:  # late peak, fast release
        return _sweep(n, rng, 400 + 2800 * np.sin(np.pi * steps ** 0.6) ** 2, (0.5, 1.7), 0.65, 3.0)
    flutter = 1.0 - 0.35 * (0.5 + 0.5 * np.sin(2 * np.pi * 18 * t))  # 5: bright flutter, airy top
    return _sweep(n, rng, 1400 + 3200 * np.sin(np.pi * steps) ** 1.2, (0.6, 1.5), 0.45, 2.0) * flutter


def _swish(variant: int, n: int, rng: np.random.Generator, steps: np.ndarray) -> np.ndarray:
    t = np.arange(n) / SAMPLE_RATE
    if variant == 0:  # rising
        return _sweep(n, rng, 900 + 1800 * steps, (0.55, 1.6), 0.3, 2.0)
    if variant == 1:  # falling
        return _sweep(n, rng, 2800 - 1900 * steps, (0.55, 1.6), 0.2, 2.2)
    if variant == 2:  # airy and narrow
        return _sweep(n, rng, np.full(8, 3200.0), (0.65, 1.5), 0.35, 2.0)
    if variant == 3:  # soft and low
        return _sweep(n, rng, 400 + 1000 * steps, (0.5, 1.8), 0.35, 1.8)
    if variant == 4:  # rise and fall
        return _sweep(n, rng, 1000 + 1600 * np.sin(np.pi * steps), (0.55, 1.6), 0.4, 2.0)
    grain = 1.0 - 0.25 * (0.5 + 0.5 * np.sin(2 * np.pi * 30 * t))  # 5: brushed grain
    return _sweep(n, rng, np.full(8, 2200.0), (0.55, 1.6), 0.3, 2.0) * grain


def _pop(variant: int, n: int, rng: np.random.Generator, tonic: float) -> np.ndarray:
    t = np.arange(n) / SAMPLE_RATE
    attack = np.clip(t / 0.002, 0.0, 1.0)
    if variant in (0, 1, 3):
        # Rounded pitch-glide pops (no broadband click): warm down, bubble up, soft thud.
        freq = {0: 190 + 430 * np.exp(-t / 0.022),
                1: 300 + 420 * (1 - np.exp(-t / 0.012)),
                3: 120 + 220 * np.exp(-t / 0.015)}[variant]
        decay = {0: 0.04, 1: 0.035, 3: 0.05}[variant]
        low, high = {0: (900.0, 2400.0), 1: (1200.0, 3000.0), 3: (400.0, 1200.0)}[variant]
        phase = 2 * np.pi * np.cumsum(freq) / SAMPLE_RATE
        body = (np.sin(phase) + 0.18 * np.sin(2 * phase)) * np.exp(-t / decay) * attack
        tap = _band_noise(n, rng, np.full(8, low), np.full(8, high)) * np.exp(-t / 0.006) * attack
        return body + 0.35 * tap / (np.max(np.abs(tap)) or 1.0)
    if variant == 2:  # wood knock: decaying modes
        body = partials(t, 680.0, [1, 1.82, 2.95], [1, 0.45, 0.2], [0.025, 0.012, 0.007]) * attack
        tap = _band_noise(n, rng, np.full(8, 1500.0), np.full(8, 4000.0)) * np.exp(-t / 0.003) * attack
        return body + 0.25 * tap / (np.max(np.abs(tap)) or 1.0)
    if variant == 4:  # pluck, tuned to the key
        ratios = [1, 2, 3, 4, 5]
        return partials(t, tonic, ratios, [1 / k for k in ratios], [0.09 / k for k in ratios]) * attack
    return partials(t, tonic, [1, 4.0, 10.0], [1, 0.3, 0.06], [0.06, 0.015, 0.006]) * attack  # 5: marimba


def _tick(variant: int, n: int, rng: np.random.Generator, tonic: float) -> np.ndarray:
    t = np.arange(n) / SAMPLE_RATE
    attack = np.clip(t / 0.0015, 0.0, 1.0)
    if variant == 0:  # two-tone
        return (np.sin(2 * np.pi * 1760 * t) * 0.7 + np.sin(2 * np.pi * 2640 * t) * 0.3) * np.exp(-t / 0.009) * attack
    if variant == 1:  # wood tick
        return _band_noise(n, rng, np.full(8, 2500.0), np.full(8, 6000.0)) * np.exp(-t / 0.004) * attack
    if variant == 2:  # glass, tuned (octaves above the key)
        f = tonic * 4 if tonic * 4 < 4200 else tonic * 2
        return partials(t, f, [1, 2.76], [1, 0.25], [0.012, 0.006]) * attack
    if variant == 3:  # soft click
        return (np.sin(2 * np.pi * 1200 * t) * 0.6 + np.sin(2 * np.pi * 1800 * t) * 0.4) * np.exp(-t / 0.007) * attack
    if variant == 4:  # digital blip, falling
        freq = 2000 + 200 * np.exp(-t / 0.01)
        return np.sin(2 * np.pi * np.cumsum(freq) / SAMPLE_RATE) * np.exp(-t / 0.012) * attack
    one = np.sin(2 * np.pi * 1900 * t) * np.exp(-t / 0.006) * attack  # 5: double tick
    shift = int(0.035 * SAMPLE_RATE)
    signal = one.copy()
    signal[shift:] += 0.55 * one[: n - shift]
    return signal


def _swell(variant: int, n: int, rng: np.random.Generator, steps: np.ndarray, tonic: float) -> np.ndarray:
    t = np.arange(n) / SAMPLE_RATE
    root = tonic / 4 if tonic / 4 >= 80 else tonic / 2  # the key's low register
    if variant == 0:  # air and a fifth
        air = _band_noise(n, rng, np.full(8, 300.0), np.full(8, 1800.0))
        tone = np.sin(2 * np.pi * root * t) * 0.5 + np.sin(2 * np.pi * root * 1.5 * t) * 0.25
        return (0.6 * air / (np.max(np.abs(air)) or 1.0) + tone) * _envelope(n, 0.35, 1.6)
    if variant == 1:  # noise riser
        return _sweep(n, rng, 400 + 2600 * steps ** 1.5, (0.5, 1.6), 0.8, 1.2)
    if variant == 2:  # shimmer with tremolo
        tone = partials(t, root * 4, [1, 1.5, 2], [1, 0.6, 0.4], [0, 0, 0]) * (0.75 + 0.25 * np.sin(2 * np.pi * 6 * t))
        air = _band_noise(n, rng, np.full(8, 2500.0), np.full(8, 6000.0))
        return (tone / 2.0 + 0.1 * air / (np.max(np.abs(air)) or 1.0)) * _envelope(n, 0.5, 1.6)
    if variant == 3:  # sub swell
        tone = partials(t, 55.0, [1, 1.5, 2], [1, 0.4, 0.3], [0, 0, 0])
        air = _band_noise(n, rng, np.full(8, 120.0), np.full(8, 600.0))
        return (tone + 0.4 * air / (np.max(np.abs(air)) or 1.0)) * _envelope(n, 0.45, 1.5)
    if variant == 4:  # reversed bell
        bell = partials(t, root * 2, [1, 2.76, 5.4], [1, 0.4, 0.15], [0.25, 0.12, 0.06])
        return bell[::-1] * _envelope(n, 0.92, 4.0)
    chord = sum(partials(t, root * 2 * ratio, [1, 2, 3], [1, 0.3, 0.1], [0, 0, 0])  # 5: warm chord
                for ratio in (1.0, 2 ** (4 / 12), 1.5))
    return chord * _envelope(n, 0.5, 1.4)


DEFAULT_SECONDS = {
    "whoosh": (0.32, 0.40, 0.26, 0.34, 0.36, 0.32),
    "swish": (0.22, 0.20, 0.18, 0.24, 0.20, 0.22),
    "pop": (0.15, 0.15, 0.12, 0.14, 0.20, 0.18),
    "tick": (0.05, 0.03, 0.06, 0.04, 0.05, 0.08),
    "swell": (0.8,) * 6,
}


def synthesize(kind: str, *, length: float | None = None, seed: int = 7, variant: int = 0,
               tonic: float = 392.0) -> np.ndarray:
    """Mono effect normalised to peak 1.0. ``variant`` (0-5) picks one of six designs of the
    same moment; ``tonic`` (Hz) tunes the tonal variants."""
    if kind not in DEFAULT_SECONDS:
        raise ValueError(f"unknown sound effect {kind!r}")
    rng = np.random.default_rng(seed)
    variant %= VARIANTS
    fixed = kind in {"pop", "tick"}
    seconds = DEFAULT_SECONDS[kind][variant] if fixed or not length else length
    n = max(64, int(seconds * SAMPLE_RATE))
    steps = np.linspace(0.0, 1.0, 64)
    if kind == "whoosh":
        signal = _whoosh(variant, n, rng, steps)
    elif kind == "swish":
        signal = _swish(variant, n, rng, steps)
    elif kind == "pop":
        signal = _pop(variant, n, rng, tonic)
    elif kind == "tick":
        signal = _tick(variant, n, rng, tonic)
    else:
        signal = _swell(variant, n, rng, steps, tonic)
    tail = min(len(signal), int(0.005 * SAMPLE_RATE))
    if tail:
        signal[-tail:] *= np.linspace(1.0, 0.0, tail)  # never an abrupt end
    peak = float(np.max(np.abs(signal))) or 1.0
    return (signal / peak).astype(np.float64)


# -- mixing ---------------------------------------------------------------------------------
def _read_audio(path: Path, ffmpeg_bin: str) -> np.ndarray:
    result = run_hidden([ffmpeg_bin, "-v", "error", "-i", str(path), "-f", "f32le", "-ac", "2", "-ar",
                         str(SAMPLE_RATE), "-"], capture_output=True, check=True)
    return np.frombuffer(result.stdout, dtype=np.float32).reshape(-1, 2).astype(np.float64)


def _speech_rms(voice: np.ndarray) -> float:
    """Narration loudness: the median RMS of its 50 ms windows that carry speech."""
    mono = np.abs(voice).max(axis=1) if voice.ndim == 2 else np.abs(voice)
    size = int(0.05 * SAMPLE_RATE)
    if len(mono) < size:
        return 0.05
    windows = np.sqrt((voice[: len(voice) // size * size].reshape(-1, size, voice.shape[1]) ** 2).mean(axis=(1, 2)))
    speech = windows[windows > np.percentile(windows, 60)]
    return float(np.median(speech)) if len(speech) else 0.05


def _active_rms(sound: np.ndarray) -> float:
    loud = np.abs(sound) > 0.1 * np.max(np.abs(sound))
    return float(np.sqrt((sound[loud] ** 2).mean())) if loud.any() else 1.0


def effects_bed(plan: RenderPlan, length: int, reference: float, choice: music_bed.MusicChoice) -> tuple[np.ndarray, dict]:
    """The effects stem (stereo, ``length`` samples) with rotated variants and humanisation."""
    events = plan_events(plan)
    bed = np.zeros((length, 2))
    rotation = Rotation(plan_seed("effects", str(choice.seed)))
    jitter = np.random.default_rng(plan_seed("effect-jitter", str(choice.seed)))
    cache: dict[tuple, np.ndarray] = {}
    played: dict[str, list[int]] = {}
    for event in events:
        variant = rotation.next(event.kind)
        degree, pitch, level = int(jitter.integers(0, 5)), jitter.uniform(-1, 1), jitter.uniform(-1, 1)
        tonal = (event.kind, variant) in TONAL
        tonic = choice.pentatonic_hz(degree, 3) if tonal else 392.0
        key = (event.kind, variant, event.length, round(tonic, 2))
        if key not in cache:
            cache[key] = synthesize(event.kind, length=event.length, seed=11 + 7 * variant + PRIORITY[event.kind],
                                    variant=variant, tonic=tonic)
        sound = cache[key] if tonal else resample(cache[key], 1.0 + PITCH_JITTER * pitch)
        gain = LEVELS[event.kind] + LEVEL_JITTER_DB * level
        sound = sound * (reference * 10 ** (gain / 20) / _active_rms(sound))
        start = int(round(event.time * SAMPLE_RATE))
        if start >= length:
            continue
        sound = sound[: length - start]
        left, right = (1 - max(0.0, event.pan)) ** 0.5, (1 + min(0.0, event.pan)) ** 0.5
        bed[start:start + len(sound), 0] += sound * left
        bed[start:start + len(sound), 1] += sound * right
        played.setdefault(event.kind, []).append(variant)
    counts = {kind: len(rows) for kind, rows in played.items()}
    repeats = sum(1 for rows in played.values() for a, b in zip(rows, rows[1:]) if a == b)
    return bed, {"events": len(events), "by_kind": counts, "variants": {k: sorted(set(v)) for k, v in played.items()},
                 "back_to_back_repeats": repeats}


def mix(plan: RenderPlan, narration: Path, output: Path, *, ffmpeg_bin: str = "ffmpeg",
        include_voice: bool = True, stems: tuple[str, ...] = ("effects", "music"),
        library: Path | None = None) -> dict:
    """Narration + effects + music -> 48 kHz stereo WAV of exactly the narration's length.
    ``include_voice=False`` with one stem writes that stem alone (an editable Premiere track)."""
    voice = _read_audio(narration, ffmpeg_bin)
    reference = max(0.005, _speech_rms(voice))
    choice = music_bed.choose(plan)
    bed = np.zeros_like(voice)
    report: dict = {"speech_rms": round(reference, 5)}
    if "effects" in stems:
        effects, info = effects_bed(plan, len(voice), reference, choice)
        bed += effects
        report.update(info)
    if "music" in stems:
        if not music_bed.BACKGROUND_MUSIC:
            report["music"] = "off"
        else:
            try:  # the music never costs the effects or the narration
                score, info = music_bed.render(plan, voice, reference, choice, library=library,
                                               ffmpeg_bin=ffmpeg_bin)
                bed += score
                report.update({"music": "mixed", **info})
            except Exception as exc:  # noqa: BLE001 - recorded, the rest of the mix stands
                report.update({"music": "skipped", "music_error": f"{type(exc).__name__}: {exc}"[:300]})
    mixed = voice + bed if include_voice else bed
    # Soft limiter: transparent below 0.89, smooth knee to full scale.
    mixed = np.where(np.abs(mixed) <= 0.89, mixed, np.sign(mixed) * (0.89 + 0.11 * np.tanh((np.abs(mixed) - 0.89) / 0.11)))
    pcm = (np.clip(mixed, -1.0, 1.0) * 32767).astype("<i2")
    output.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(output), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(SAMPLE_RATE)
        handle.writeframes(pcm.tobytes())
    return report


def mix_or_narration(plan: RenderPlan, narration: Path, output: Path, *, ffmpeg_bin: str = "ffmpeg",
                     effects: bool = True, music: bool = True,
                     library: Path | None = None) -> tuple[Path, dict]:
    """The mixed track, or the narration itself when everything is off or fails (recorded).

    ``effects`` / ``music`` are the operator's switches (web and desktop); the module
    switches ``SOUND_EFFECTS`` / ``music.BACKGROUND_MUSIC`` turn a layer off for every job."""
    stems = tuple(name for name, on in (("effects", effects and SOUND_EFFECTS),
                                        ("music", music and music_bed.BACKGROUND_MUSIC)) if on)
    if not stems:
        return narration, {"sound_effects": "off", "music": "off"}
    try:
        report = mix(plan, narration, output, ffmpeg_bin=ffmpeg_bin, stems=stems, library=library)
    except (OSError, ValueError, subprocess.CalledProcessError, MemoryError) as exc:
        return narration, {"sound_effects": "skipped", "error": str(exc)[:300]}
    return output, {"sound_effects": "mixed" if "effects" in stems else "off", "music": "off", **report}
