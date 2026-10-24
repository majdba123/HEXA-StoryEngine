"""Web-specific bridge to the shared, Qt-free Intro Zoom renderer.

The browser sends only image-space selection coordinates; all media paths are
derived from authenticated upload storage, never from client-supplied paths.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from app.features.intro_zoom.models import IntroZoomConfig
from app.features.intro_zoom.validation import AUDIO_TYPES, IMAGE_TYPES, preflight

IMAGE_LIMIT = 200 * 1024 * 1024
VOICE_LIMIT = 64 * 1024 * 1024


def selection(value: object) -> dict[str, float]:
    if not isinstance(value, dict) or set(value) != {"focus_x", "focus_y", "magnification"}:
        raise ValueError("Intro Zoom needs target coordinates and magnification")
    if any(type(value[name]) not in (int, float) for name in value):
        raise ValueError("Intro Zoom selection values must be numbers")
    choice = {key: float(value[key]) for key in ("focus_x", "focus_y", "magnification")}
    # Use the same geometry validation as desktop without requiring a media file yet.
    IntroZoomConfig(Path("image.png"), Path("voice.wav"), **choice)
    return choice


def prepare(directory: Path, image: Path, voice: Path, choice: dict,
            *, ffprobe_bin: str = "ffprobe", ffmpeg_bin: str = "ffmpeg") -> IntroZoomConfig:
    """Validate untrusted media before admitting a generation job."""
    checked = selection(choice)
    if image.suffix.lower() not in IMAGE_TYPES or voice.suffix.lower() not in AUDIO_TYPES:
        raise ValueError("Unsupported Intro Zoom image or audio format")
    if not image.is_file() or not voice.is_file():
        raise ValueError("Intro Zoom image or voice is missing")
    if image.stat().st_size <= 0 or image.stat().st_size > IMAGE_LIMIT:
        raise ValueError("Intro Zoom image exceeds its safe size")
    if voice.stat().st_size <= 0 or voice.stat().st_size > VOICE_LIMIT:
        raise ValueError("Intro Zoom voice exceeds its safe size")
    directory.mkdir(parents=True, exist_ok=True)
    image_path = directory / ("intro-image" + image.suffix.lower())
    voice_path = directory / ("intro-voice" + voice.suffix.lower())
    if image != image_path:
        shutil.copyfile(image, image_path)
    if voice != voice_path:
        shutil.copyfile(voice, voice_path)
    if image_path.is_symlink() or voice_path.is_symlink():
        raise ValueError("Intro Zoom symlinks are not accepted")
    config = IntroZoomConfig(image_path, voice_path, **checked)
    preflight(config, ffprobe_bin=ffprobe_bin, ffmpeg_bin=ffmpeg_bin)
    return config


def from_job(package_path: Path, choice: object) -> IntroZoomConfig:
    """Reconstruct immutable config on worker/retry using its validated input folder."""
    checked = selection(choice)
    directory = package_path.parent
    images = [path for suffix in IMAGE_TYPES
              if (path := directory / ("intro-image" + suffix)).is_file()
              and not path.is_symlink()]
    voices = [path for suffix in AUDIO_TYPES
              if (path := directory / ("intro-voice" + suffix)).is_file()
              and not path.is_symlink()]
    if len(images) != 1 or len(voices) != 1:
        raise ValueError("Intro Zoom media is missing or ambiguous; cannot generate")
    return IntroZoomConfig(images[0], voices[0], **checked)
