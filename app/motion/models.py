from __future__ import annotations

from dataclasses import dataclass
from math import hypot, isfinite
from typing import Any


@dataclass(frozen=True, slots=True)
class MotionKeyframe:
    """Backend-neutral transform relative to the Composition target.

    ``dx``/``dy`` are normalized canvas offsets. ``scale`` is relative to the
    Composition-authored size. Motion never owns the final resting position or size;
    semantic settle and final keyframes must return to (0, 0, 1).
    """

    progress: float
    dx: float = 0.0
    dy: float = 0.0
    scale: float = 1.0
    easing: str = "ease_out_cubic"

    def __post_init__(self) -> None:
        values = (self.progress, self.dx, self.dy, self.scale)
        if not all(isfinite(value) for value in values):
            raise ValueError("motion keyframe values must be finite")
        if not 0.0 <= self.progress <= 1.0:
            raise ValueError("motion keyframe progress must be in [0, 1]")
        if self.scale <= 0.0:
            raise ValueError("motion keyframe scale must be positive")


@dataclass(frozen=True, slots=True)
class MotionProgram:
    """Deterministic transform trajectory ending at the Composition target."""

    name: str
    keyframes: tuple[MotionKeyframe, ...]
    settle_progress: float = 1.0

    def __post_init__(self) -> None:
        if len(self.keyframes) < 2:
            raise ValueError("motion program requires at least two keyframes")
        progress = [frame.progress for frame in self.keyframes]
        if progress[0] != 0.0 or progress[-1] != 1.0:
            raise ValueError("motion program must start at progress 0 and end at progress 1")
        if any(right <= left for left, right in zip(progress, progress[1:])):
            raise ValueError("motion program keyframes must be strictly increasing")
        if not 0.0 < self.settle_progress <= 1.0:
            raise ValueError("motion settle_progress must be in (0, 1]")

        final = self.keyframes[-1]
        if abs(final.dx) > 1e-9 or abs(final.dy) > 1e-9 or abs(final.scale - 1.0) > 1e-9:
            raise ValueError("motion program must finish on the Composition target")
        settle = next((f for f in self.keyframes if abs(f.progress - self.settle_progress) <= 1e-9), None)
        if settle is None:
            raise ValueError("motion settle_progress must match an authored keyframe")
        if abs(settle.dx) > 1e-9 or abs(settle.dy) > 1e-9 or abs(settle.scale - 1.0) > 1e-9:
            raise ValueError("semantic settle keyframe must be on the Composition target")

    @property
    def travel_distance(self) -> float:
        distance = 0.0
        previous = self.keyframes[0]
        for current in self.keyframes[1:]:
            distance += hypot(current.dx - previous.dx, current.dy - previous.dy)
            distance += abs(current.scale - previous.scale) * 0.20
            previous = current
        return distance

    def to_payload(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "settle_progress": self.settle_progress,
            "keyframes": [
                {
                    "progress": frame.progress,
                    "dx": frame.dx,
                    "dy": frame.dy,
                    "scale": frame.scale,
                    "easing": frame.easing,
                }
                for frame in self.keyframes
            ],
        }
