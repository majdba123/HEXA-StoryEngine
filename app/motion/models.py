from __future__ import annotations

from dataclasses import dataclass
from math import hypot, isfinite
from typing import Any


@dataclass(frozen=True, slots=True)
class MotionKeyframe:
    """Backend-neutral offset keyframe relative to the Composition target.

    ``dx`` and ``dy`` are normalized canvas offsets. A value of 0.05 means five
    percent of the output width/height. Motion never owns the final resting
    position; the final keyframe must return to the Composition target at (0, 0).
    """

    progress: float
    dx: float = 0.0
    dy: float = 0.0
    easing: str = "ease_out_cubic"

    def __post_init__(self) -> None:
        values = (self.progress, self.dx, self.dy)
        if not all(isfinite(value) for value in values):
            raise ValueError("motion keyframe values must be finite")
        if not 0.0 <= self.progress <= 1.0:
            raise ValueError("motion keyframe progress must be in [0, 1]")


@dataclass(frozen=True, slots=True)
class MotionProgram:
    """A deterministic motion trajectory ending at the Composition target."""

    name: str
    keyframes: tuple[MotionKeyframe, ...]

    def __post_init__(self) -> None:
        if len(self.keyframes) < 2:
            raise ValueError("motion program requires at least two keyframes")
        progress = [frame.progress for frame in self.keyframes]
        if progress[0] != 0.0 or progress[-1] != 1.0:
            raise ValueError("motion program must start at progress 0 and end at progress 1")
        if any(right <= left for left, right in zip(progress, progress[1:])):
            raise ValueError("motion program keyframes must be strictly increasing")
        final = self.keyframes[-1]
        if abs(final.dx) > 1e-9 or abs(final.dy) > 1e-9:
            raise ValueError("motion program must settle on the Composition target")

    @property
    def travel_distance(self) -> float:
        """Approximate normalized path length used only for pacing decisions."""

        distance = 0.0
        previous = self.keyframes[0]
        for current in self.keyframes[1:]:
            distance += hypot(current.dx - previous.dx, current.dy - previous.dy)
            previous = current
        return distance

    def to_payload(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "keyframes": [
                {
                    "progress": frame.progress,
                    "dx": frame.dx,
                    "dy": frame.dy,
                    "easing": frame.easing,
                }
                for frame in self.keyframes
            ],
        }
