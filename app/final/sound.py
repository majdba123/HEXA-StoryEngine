"""Sound design: motion-driven sound effects mixed under the narration (2026-10-21).

Retention review: the videos carried the narration alone. Explainer practice keeps the voice
on top, effects 6-12 dB below it and sparse (over-use turns busy fast). Every effect here is
driven by an event the edit already owns, so it lands on the exact frame of its motion:

* ``whoosh``  a character swap (Boundary scene whip), panned the way the scene travels;
* ``swish``   a clear between ideas (scene fade), softer and shorter;
* ``pop``     the first element of each new picture landing;
* ``tick``    a large keyword appearing (font scale >= 1.0), very quiet;
* ``swell``   the grey-wash climax of an idea (focus wash), a soft rise under its ramp.

Effects are synthesized (numpy, deterministic, no licensing), at least MIN_GAP apart (the
higher priority wins), levelled against the narration's own speech level and summed through
a soft limiter. The mixed track keeps the narration's exact length and sample rate, so A/V
timing and every QA duration check are unchanged. A failure never stops a render: the
narration alone is used and the reason is recorded.
"""

from __future__ import annotations

import subprocess
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from app.models import RenderPlan
from app.shared.process import run_hidden

SOUND_EFFECTS = True
SAMPLE_RATE = 48_000
MIN_GAP = 0.25  # seconds between two effects (restraint)
TICK_MIN_FONT_SCALE = 1.0
# Loudness (RMS while sounding) of each effect relative to the narration's speech RMS (dB):
# voice on top, effects 8-16 dB under it.
LEVELS = {"whoosh": -8.0, "swish": -12.0, "pop": -9.0, "tick": -16.0, "swell": -12.0}
# A tick is the lightest accent: it plays only with no other effect this close.
TICK_CLEARANCE = 0.6
PRIORITY = {"whoosh": 0, "swell": 1, "swish": 2, "pop": 3, "tick": 4}


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
    for beat_id, beat in beats.items():
        starts = [float(cue.start) for cue in plan.motion if cue.beat_id == beat_id]
        if starts:
            events.append(SoundEvent("pop", max(float(beat.start), min(starts))))
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
        gap = TICK_CLEARANCE if event.kind == "tick" else MIN_GAP
        if 0.0 <= event.time < plan.duration and all(abs(event.time - other.time) >= gap for other in chosen):
            chosen.append(event)
    return sorted(chosen, key=lambda row: row.time)


# -- synthesis (numpy only) -------------------------------------------------------------------
def _envelope(n: int, attack: float, curve: float = 3.0) -> np.ndarray:
    t = np.linspace(0.0, 1.0, n, endpoint=False)
    rise = np.clip(t / max(attack, 1e-6), 0.0, 1.0)
    fall = np.clip((1.0 - t) / max(1.0 - attack, 1e-6), 0.0, 1.0) ** curve
    return rise * rise * (3 - 2 * rise) * fall


def _band_noise(n: int, rng: np.random.Generator, low: np.ndarray, high: np.ndarray) -> np.ndarray:
    """Noise through a moving band-pass (overlap-add STFT, band edges per hop)."""
    size, hop = 1024, 256
    noise = rng.standard_normal(n + size)
    out = np.zeros(n + size)
    window = np.hanning(size)
    freqs = np.fft.rfftfreq(size, 1.0 / SAMPLE_RATE)
    for index, start in enumerate(range(0, n, hop)):
        position = min(len(low) - 1, int(index * hop * len(low) / max(1, n)))
        lo, hi = low[position], high[position]
        mask = np.clip((freqs - lo * 0.7) / max(1.0, lo * 0.3), 0, 1) * np.clip((hi * 1.3 - freqs) / max(1.0, hi * 0.3), 0, 1)
        spectrum = np.fft.rfft(noise[start:start + size] * window) * mask
        out[start:start + size] += np.fft.irfft(spectrum, size) * window
    return out[:n]


def synthesize(kind: str, *, length: float | None = None, seed: int = 7) -> np.ndarray:
    """Mono effect normalised to peak 1.0."""
    rng = np.random.default_rng(seed)
    if kind in {"whoosh", "swish"}:
        seconds = length or (0.32 if kind == "whoosh" else 0.22)
        n = int(seconds * SAMPLE_RATE)
        steps = np.linspace(0.0, 1.0, 64)
        center = 500 + 2600 * np.sin(np.pi * steps) ** 1.5 if kind == "whoosh" else 900 + 1800 * steps
        signal = _band_noise(n, rng, center * 0.55, center * 1.6) * _envelope(n, 0.45 if kind == "whoosh" else 0.3, 2.0)
    elif kind == "pop":
        # A warm, rounded pop: a short downward pitch glide with a 2 ms attack (no broadband
        # click) and a soft mid-band tap for definition.
        n = int(0.15 * SAMPLE_RATE)
        t = np.arange(n) / SAMPLE_RATE
        freq = 190 + 430 * np.exp(-t / 0.022)
        phase = 2 * np.pi * np.cumsum(freq) / SAMPLE_RATE
        attack = np.clip(t / 0.002, 0.0, 1.0)
        body = (np.sin(phase) + 0.18 * np.sin(2 * phase)) * np.exp(-t / 0.04) * attack
        tap = _band_noise(n, rng, np.full(8, 900.0), np.full(8, 2400.0)) * np.exp(-t / 0.006) * attack
        signal = body + 0.35 * tap / (np.max(np.abs(tap)) or 1.0)
    elif kind == "tick":
        n = int(0.05 * SAMPLE_RATE)
        t = np.arange(n) / SAMPLE_RATE
        attack = np.clip(t / 0.0015, 0.0, 1.0)
        signal = (np.sin(2 * np.pi * 1760 * t) * 0.7 + np.sin(2 * np.pi * 2640 * t) * 0.3) * np.exp(-t / 0.009) * attack
    elif kind == "swell":
        seconds = length or 0.8
        n = int(seconds * SAMPLE_RATE)
        t = np.arange(n) / SAMPLE_RATE
        air = _band_noise(n, rng, np.full(8, 300.0), np.full(8, 1800.0)) * 0.6
        tone = np.sin(2 * np.pi * 110 * t) * 0.5 + np.sin(2 * np.pi * 165 * t) * 0.25
        signal = (air + tone) * _envelope(n, 0.35, 1.6)
    else:
        raise ValueError(f"unknown sound effect {kind!r}")
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


def mix(plan: RenderPlan, narration: Path, output: Path, *, ffmpeg_bin: str = "ffmpeg",
        include_voice: bool = True) -> dict:
    """Narration + effects -> 48 kHz stereo WAV of exactly the narration's length
    (``include_voice=False``: the effects stem alone, for an editable second track)."""
    voice = _read_audio(narration, ffmpeg_bin)
    events = plan_events(plan)
    reference = max(0.005, _speech_rms(voice))
    bed = np.zeros_like(voice)
    cache: dict[tuple[str, float | None], np.ndarray] = {}
    for index, event in enumerate(events):
        key = (event.kind, event.length)
        if key not in cache:
            cache[key] = synthesize(event.kind, length=event.length, seed=11 + len(cache))
        base = cache[key]
        sound = base * (reference * 10 ** (LEVELS[event.kind] / 20) / _active_rms(base))
        start = int(round(event.time * SAMPLE_RATE))
        if start >= len(bed):
            continue
        sound = sound[: len(bed) - start]
        left, right = (1 - max(0.0, event.pan)) ** 0.5, (1 + min(0.0, event.pan)) ** 0.5
        bed[start:start + len(sound), 0] += sound * left
        bed[start:start + len(sound), 1] += sound * right
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
    counts: dict[str, int] = {}
    for event in events:
        counts[event.kind] = counts.get(event.kind, 0) + 1
    return {"events": len(events), "by_kind": counts, "speech_rms": round(reference, 5)}


def mix_or_narration(plan: RenderPlan, narration: Path, output: Path, *, ffmpeg_bin: str = "ffmpeg") -> tuple[Path, dict]:
    """The mixed track, or the narration itself when effects are off or fail (recorded)."""
    if not SOUND_EFFECTS:
        return narration, {"sound_effects": "off"}
    try:
        report = mix(plan, narration, output, ffmpeg_bin=ffmpeg_bin)
    except (OSError, ValueError, subprocess.CalledProcessError, MemoryError) as exc:
        return narration, {"sound_effects": "skipped", "error": str(exc)[:300]}
    return output, {"sound_effects": "mixed", **report}
