from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True, slots=True)
class HandlerResult:
    success: bool
    invalidate_from_stage: str | None = None
    message: str = ""


RecoveryHandler = Callable[[dict], HandlerResult]


def retry_cutout(context: dict) -> HandlerResult:
    return HandlerResult(True, "cutout", "retry asset extraction with stricter matte policy")


def rebuild_story_timing(context: dict) -> HandlerResult:
    return HandlerResult(True, "story", "rebuild narration-to-visual handoff timing")


def rebuild_composition(context: dict) -> HandlerResult:
    return HandlerResult(True, "composition", "rebuild composition for stronger occupancy")


def rebuild_motion(context: dict) -> HandlerResult:
    return HandlerResult(True, "motion", "rebuild reveal/handoff motion")


def rerender(context: dict) -> HandlerResult:
    return HandlerResult(True, "render", "rebuild rendered video from the current verified plan")


def remux_audio(context: dict) -> HandlerResult:
    return HandlerResult(True, "final", "rebuild final audio/video mux")


HANDLERS: dict[str, RecoveryHandler] = {
    "retry_cutout": retry_cutout,
    "rebuild_story_timing": rebuild_story_timing,
    "rebuild_composition": rebuild_composition,
    "rebuild_motion": rebuild_motion,
    "rerender": rerender,
    "remux_audio": remux_audio,
}
