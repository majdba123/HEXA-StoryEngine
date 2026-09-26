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


def repair_text_layout(context: dict) -> HandlerResult:
    return HandlerResult(
        True,
        "composition",
        "recompose text against final visual timing and degrade only unsafe optional cues",
    )


def repair_motion_readability(context: dict) -> HandlerResult:
    return HandlerResult(
        True,
        "motion_segment",
        "raise only rendered segments proven below the shared readability floor",
    )


def rerender(context: dict) -> HandlerResult:
    return HandlerResult(True, "render", "rebuild rendered video from the current verified plan")


def rerender_strict_handoff(context: dict) -> HandlerResult:
    return HandlerResult(
        True,
        "render",
        "rerender with semantic-safe maximum boundary coverage",
    )


def remux_audio(context: dict) -> HandlerResult:
    return HandlerResult(True, "final", "rebuild final audio/video mux")


HANDLERS: dict[str, RecoveryHandler] = {
    "retry_cutout": retry_cutout,
    "rebuild_story_timing": rebuild_story_timing,
    "rebuild_composition": rebuild_composition,
    "rebuild_motion": rebuild_motion,
    "repair_text_layout": repair_text_layout,
    "repair_motion_readability": repair_motion_readability,
    "rerender": rerender,
    "rerender_strict_handoff": rerender_strict_handoff,
    "remux_audio": remux_audio,
}
