from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Rect:
    x: float
    y: float
    width: float
    height: float


def fitted_rect(container_width: float, container_height: float,
                image_width: float, image_height: float) -> Rect:
    """The exact contain rectangle, including letterboxing, in widget logical pixels."""
    if min(container_width, container_height, image_width, image_height) <= 0:
        raise ValueError("Image and preview dimensions must be positive")
    scale = min(container_width / image_width, container_height / image_height)
    width, height = image_width * scale, image_height * scale
    return Rect((container_width - width) / 2, (container_height - height) / 2,
                width, height)


def click_to_source(x: float, y: float, container_width: float, container_height: float,
                    image_width: float, image_height: float) -> tuple[float, float] | None:
    area = fitted_rect(container_width, container_height, image_width, image_height)
    if not (area.x <= x < area.x + area.width and area.y <= y < area.y + area.height):
        return None
    return ((x - area.x) / area.width, (y - area.y) / area.height)


def final_crop(image_width: int, image_height: int, target_width: int,
               target_height: int, focus_x: float, focus_y: float,
               magnification: float) -> Rect:
    """Aspect-correct crop centered on the click; edge overflow gets treated in render."""
    ratio = target_width / target_height
    base_width = min(float(image_width), image_height * ratio)
    base_height = base_width / ratio
    width, height = base_width / magnification, base_height / magnification
    return Rect(focus_x * image_width - width / 2,
                focus_y * image_height - height / 2, width, height)


def smoothstep(progress: float) -> float:
    t = min(1.0, max(0.0, progress))
    return t * t * (3.0 - 2.0 * t)


def animated_crop(image_width: int, image_height: int, end: Rect,
                  frame: int, frames: int) -> Rect:
    # Brief whole-image hold, then a cubic ease. The final frame reaches the target.
    t = smoothstep((frame / max(1, frames - 1) - 0.12) / 0.88)
    return Rect(end.x * t, end.y * t,
                image_width + (end.width - image_width) * t,
                image_height + (end.height - image_height) * t)
