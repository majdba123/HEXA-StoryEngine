from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from app.targets.models import VisualTargetProfile
from app.targets.youtube.profile import YOUTUBE_16_9

_ACTIVE: ContextVar[VisualTargetProfile | None] = ContextVar("hexa_visual_target", default=None)


def active_target() -> VisualTargetProfile:
    """The target the shared visual engine is authoring geometry for right now.

    Shared Composition/Motion/Text/Boundary code reads frame facts from here instead of
    hard-coding 1920x1080. Outside an explicit ``visual_target`` scope the certified
    16:9 reference applies, so legacy callers behave exactly as before.
    """
    return _ACTIVE.get() or YOUTUBE_16_9


def frame_size() -> tuple[int, int]:
    return active_target().frame


@contextmanager
def visual_target(target: VisualTargetProfile) -> Iterator[VisualTargetProfile]:
    token = _ACTIVE.set(target)
    try:
        yield target
    finally:
        _ACTIVE.reset(token)
