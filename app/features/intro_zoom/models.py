from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path


FPS = 30
DEFAULT_FRAMES = 75
MAX_FRAMES = 90


@dataclass(frozen=True, slots=True)
class IntroZoomConfig:
    image: Path
    audio: Path
    focus_x: float
    focus_y: float
    magnification: float = 2.5

    def __post_init__(self) -> None:
        if not all(math.isfinite(value) for value in
                   (self.focus_x, self.focus_y, self.magnification)):
            raise ValueError("Intro target and magnification must be finite")
        if not (0.0 <= self.focus_x <= 1.0 and 0.0 <= self.focus_y <= 1.0):
            raise ValueError("Intro target must be inside the source image")
        if not 1.25 <= self.magnification <= 8.0:
            raise ValueError("Intro magnification must be between 1.25 and 8")


@dataclass(frozen=True, slots=True)
class PreparedIntro:
    config: IntroZoomConfig
    image_width: int
    image_height: int
    audio_duration: float
    frames: int

    @property
    def duration(self) -> float:
        return self.frames / FPS

    def metadata(self) -> dict:
        return {
            "enabled": True,
            "focus": [round(self.config.focus_x, 6), round(self.config.focus_y, 6)],
            "magnification": self.config.magnification,
            "image_size": [self.image_width, self.image_height],
            "voice_duration": round(self.audio_duration, 6),
            "duration": self.duration,
            "frames": self.frames,
            "fps": FPS,
        }
