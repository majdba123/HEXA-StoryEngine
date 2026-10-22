from __future__ import annotations

import json
import math
import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from app.features.intro_zoom.models import DEFAULT_FRAMES, FPS, MAX_FRAMES, IntroZoomConfig, PreparedIntro
from app.shared.process import run_hidden


IMAGE_TYPES = {".png", ".jpg", ".jpeg", ".webp"}
AUDIO_TYPES = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg"}
MAX_IMAGE_PIXELS = 48_000_000
MAX_IMAGE_BYTES = 150 * 1024 * 1024


def open_image(path: Path) -> Image.Image:
    if path.suffix.lower() not in IMAGE_TYPES or not path.is_file():
        raise ValueError("Choose a PNG, JPEG or WebP intro image")
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise ValueError(f"Intro image cannot be read: {exc}") from exc
    if size > 200 * 1024 * 1024:
        raise ValueError("Intro image file is too large")
    try:
        with Image.open(path) as source:
            if source.format not in {"PNG", "JPEG", "WEBP"}:
                raise ValueError("Intro image contents do not match a supported format")
            width, height = source.size
            if (min(width, height) < 32 or width * height > MAX_IMAGE_PIXELS
                    or width * height * 4 > MAX_IMAGE_BYTES):
                raise ValueError("Intro image dimensions or decoded memory exceed safe limits")
            source.load()
            corrected = ImageOps.exif_transpose(source)
            return corrected.convert("RGB")
    except (OSError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
        raise ValueError(f"Intro image is unreadable: {exc}") from exc


def probe_voice(path: Path, ffprobe_bin: str = "ffprobe", ffmpeg_bin: str = "ffmpeg") -> float:
    if path.suffix.lower() not in AUDIO_TYPES or not path.is_file():
        raise ValueError("Choose a supported intro audio file")
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise ValueError(f"Intro audio cannot be read: {exc}") from exc
    if size > 64 * 1024 * 1024:
        raise ValueError("Intro audio file is too large for a 3-second voice")
    try:
        result = run_hidden(
            [ffprobe_bin, "-v", "error", "-select_streams", "a:0", "-show_entries",
             "stream=codec_type,duration,sample_rate:format=duration", "-of", "json", str(path)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
        )
        if result.returncode:
            raise ValueError("Intro audio cannot be probed")
        data = json.loads(result.stdout)
        stream = next((row for row in data.get("streams", [])
                       if row.get("codec_type") == "audio"), None)
        if stream is None:
            raise ValueError("Intro audio has no readable audio stream")
        raw_duration = stream.get("duration") or data.get("format", {}).get("duration")
        duration = float(raw_duration)
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError("Intro audio has no valid duration")
        if duration > 3.0:
            raise ValueError("Intro audio must be no longer than 3 seconds")
        # A readable header alone is not proof that the short voice can be decoded.
        decoded = run_hidden(
            [ffmpeg_bin, "-v", "error", "-xerror", "-i", str(path),
             "-map", "0:a:0", "-f", "null", "-"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
        )
        if decoded.returncode:
            raise ValueError("Intro audio cannot be decoded")
        return duration
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError, TypeError) as exc:
        raise ValueError(f"Intro audio validation failed: {exc}") from exc


def preflight(config: IntroZoomConfig, *, ffprobe_bin: str = "ffprobe",
              ffmpeg_bin: str = "ffmpeg", workspace: Path | None = None) -> PreparedIntro:
    if not shutil.which(ffprobe_bin) or not shutil.which(ffmpeg_bin):
        raise ValueError("FFmpeg and FFprobe are required for Intro Zoom")
    if workspace is not None:
        workspace.mkdir(parents=True, exist_ok=True)
        probe = workspace / ".intro-write-check"
        try:
            probe.write_bytes(b"ok")
        except OSError as exc:
            raise ValueError(f"Intro workspace is not writable: {exc}") from exc
        finally:
            probe.unlink(missing_ok=True)
    image = open_image(config.image)
    try:
        duration = probe_voice(config.audio, ffprobe_bin, ffmpeg_bin)
        frames = min(MAX_FRAMES, max(DEFAULT_FRAMES, math.ceil(duration * FPS - 1e-9)))
        return PreparedIntro(config, image.width, image.height, duration, frames)
    finally:
        image.close()
