from __future__ import annotations

import math
from collections.abc import Callable


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def linear(progress: float) -> float:
    return _clamp(progress)


def ease_in_cubic(progress: float) -> float:
    progress = _clamp(progress)
    return progress**3


def ease_out_cubic(progress: float) -> float:
    progress = _clamp(progress)
    return 1.0 - (1.0 - progress) ** 3


def ease_in_out_cubic(progress: float) -> float:
    progress = _clamp(progress)
    if progress < 0.5:
        return 4.0 * progress**3
    return 1.0 - ((-2.0 * progress + 2.0) ** 3) / 2.0


def smoothstep(progress: float) -> float:
    progress = _clamp(progress)
    return progress * progress * (3.0 - 2.0 * progress)


def ease_out_expo(progress: float) -> float:
    progress = _clamp(progress)
    if progress >= 1.0:
        return 1.0
    return 1.0 - math.pow(2.0, -10.0 * progress)


def ease_out_back(progress: float) -> float:
    """Robert Penner-style back easing with a restrained standard overshoot."""

    progress = _clamp(progress)
    c1 = 1.70158
    c3 = c1 + 1.0
    shifted = progress - 1.0
    return 1.0 + c3 * shifted**3 + c1 * shifted**2


_EASINGS: dict[str, Callable[[float], float]] = {
    "linear": linear,
    "ease_in_cubic": ease_in_cubic,
    "ease_out_cubic": ease_out_cubic,
    "ease_in_out_cubic": ease_in_out_cubic,
    "smoothstep": smoothstep,
    "ease_out_expo": ease_out_expo,
    "ease_out_back": ease_out_back,
}


def sample_easing(name: str, progress: float) -> float:
    try:
        easing = _EASINGS[name]
    except KeyError as exc:
        raise ValueError(f"unknown easing: {name}") from exc
    return easing(progress)
