"""Small numpy synthesis toolkit shared by the sound effects and the background music.

Everything is deterministic (an explicit ``numpy.random.Generator``), band-limited (no
aliasing partials above 18 kHz) and click-free (every voice has a smooth attack and release).
"""

from __future__ import annotations

import hashlib

import numpy as np

SAMPLE_RATE = 48_000
NYQUIST_GUARD = 18_000.0


def plan_seed(*parts: str) -> int:
    """A stable seed from text (Python's ``hash`` changes per process)."""
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "little")


def envelope(n: int, attack: float, curve: float = 3.0) -> np.ndarray:
    """Smoothstep rise over ``attack`` (fraction of n), power-curve fall to zero."""
    t = np.linspace(0.0, 1.0, n, endpoint=False)
    rise = np.clip(t / max(attack, 1e-6), 0.0, 1.0)
    fall = np.clip((1.0 - t) / max(1.0 - attack, 1e-6), 0.0, 1.0) ** curve
    return rise * rise * (3 - 2 * rise) * fall


def adsr(n: int, attack: float, release: float) -> np.ndarray:
    """Seconds-based attack/release (sustain 1), raised-cosine edges."""
    out = np.ones(n)
    a = min(n, max(1, int(attack * SAMPLE_RATE)))
    r = min(n - a, max(1, int(release * SAMPLE_RATE))) if n > a else 0
    out[:a] = 0.5 - 0.5 * np.cos(np.linspace(0.0, np.pi, a))
    if r > 0:
        out[n - r:] *= 0.5 + 0.5 * np.cos(np.linspace(0.0, np.pi, r))
    return out


def band_noise(n: int, rng: np.random.Generator, low: np.ndarray, high: np.ndarray) -> np.ndarray:
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
    return out[:n] / 1.5  # hann^2 overlap-add gain at hop = size/4


def partials(t: np.ndarray, freq: float, ratios: list[float], amps: list[float], decays: list[float],
             phase: float = 0.0) -> np.ndarray:
    """Sum of exponentially decaying sine partials (decay in seconds; 0 = sustained)."""
    out = np.zeros_like(t)
    for ratio, amp, decay in zip(ratios, amps, decays):
        f = freq * ratio
        if f >= NYQUIST_GUARD:
            continue
        tone = np.sin(2 * np.pi * f * t + phase * ratio)
        out += amp * tone * (np.exp(-t / decay) if decay > 0 else 1.0)
    return out


def lowpass(signal: np.ndarray, cutoff: float, slope: float = 2.0) -> np.ndarray:
    """Zero-phase spectral low-pass with a smooth roll-off (whole buffer, mono or stereo)."""
    spectrum = np.fft.rfft(signal, axis=0)
    freqs = np.fft.rfftfreq(signal.shape[0], 1.0 / SAMPLE_RATE)
    gain = 1.0 / (1.0 + (freqs / max(cutoff, 1.0)) ** (2 * slope))
    if signal.ndim == 2:
        gain = gain[:, None]
    return np.fft.irfft(spectrum * gain, n=signal.shape[0], axis=0)


def resample(signal: np.ndarray, ratio: float) -> np.ndarray:
    """Pitch/speed change by ``ratio`` (>1 higher and shorter), linear interpolation."""
    if abs(ratio - 1.0) < 1e-6:
        return signal
    n = max(2, int(len(signal) / ratio))
    return np.interp(np.arange(n) * ratio, np.arange(len(signal)), signal)


def note_hz(midi: float) -> float:
    return 440.0 * 2 ** ((midi - 69) / 12)
