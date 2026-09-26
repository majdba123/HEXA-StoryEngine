from __future__ import annotations

import json
import subprocess
from pathlib import Path

import numpy as np

from app.shared.errors import DependencyUnavailableError, StageFailedError
from app.shared.process import run_hidden


def probe_duration(path: Path, ffprobe_bin: str = "ffprobe") -> float:
    command = [
        ffprobe_bin,
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "json",
        str(path),
    ]
    try:
        result = run_hidden(command, check=True, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise DependencyUnavailableError(
            "ffprobe is not available",
            details={"code": "FFPROBE_UNAVAILABLE", "binary": ffprobe_bin},
        ) from exc
    except subprocess.CalledProcessError as exc:
        raise StageFailedError(
            "ffprobe failed",
            details={"code": "MEDIA_PROBE_FAILED", "stderr": exc.stderr[-2000:]},
        ) from exc
    try:
        payload = json.loads(result.stdout)
        duration = float(payload["format"]["duration"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise StageFailedError(
            "ffprobe returned invalid duration metadata",
            details={"code": "MEDIA_PROBE_INVALID_METADATA"},
        ) from exc
    if duration <= 0:
        raise StageFailedError(
            "media duration is invalid",
            details={"code": "MEDIA_DURATION_INVALID", "duration": duration},
        )
    return duration



def decode_audio_mono(
    path: Path,
    ffmpeg_bin: str = "ffmpeg",
    *,
    sample_rate: int = 16000,
) -> np.ndarray:
    """Decode media to a mono float32 waveform without opening a child console."""
    command = [
        ffmpeg_bin,
        "-nostdin",
        "-threads",
        "0",
        "-i",
        str(path),
        "-f",
        "s16le",
        "-ac",
        "1",
        "-acodec",
        "pcm_s16le",
        "-ar",
        str(sample_rate),
        "-",
    ]
    try:
        result = run_hidden(command, check=True, capture_output=True)
    except FileNotFoundError as exc:
        raise DependencyUnavailableError("ffmpeg is not available") from exc
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or b"").decode("utf-8", errors="replace")
        raise StageFailedError(
            "ffmpeg audio decode failed",
            details={"stderr": stderr[-2000:]},
        ) from exc

    waveform = np.frombuffer(result.stdout, dtype=np.int16).astype(np.float32)
    if waveform.size == 0:
        raise StageFailedError("ffmpeg audio decode produced no samples")
    return waveform / 32768.0
