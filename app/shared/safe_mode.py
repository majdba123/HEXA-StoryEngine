"""Safer planning levels: the safe-level ladder of a generation (2026-10-21).

A render that stops helps nobody (user direction 2026-10-21). Every owner stage first
repairs its own findings (Story carriers, alignment, pre-encode motion QA). When a target
still cannot be planned, the pipeline plans it again with the newest optional craft
layers switched off — the edit the tool produced before they existed, which the certified
suites cover — instead of stopping. The shared semantic plan (alignment, Vision, cutouts,
Story, Text selection) is reused; only the per-target planning runs again.

Level 1 removes the newest staging layers (focus staging, idea spread, idea climax wash,
idea boards).
Level 2 also removes the scene whip and the late accent passes (landing, relation
interaction, spoken pulse, motion blur). Each step down is recorded in the manifest.
"""

from __future__ import annotations

import contextlib
import importlib
from collections.abc import Iterator

from app.shared.errors import DependencyUnavailableError, GenerationCancelledError, StageFailedError

SAFE_LEVELS = True
MAX_LEVEL = 2
# From this level the pipeline skips its late accent passes.
LATE_ACCENTS_OFF = 2

LEVELS: dict[int, dict[str, dict[str, object]]] = {
    1: {
        "app.composition.focus_staging": {"FOCUS_STAGING": False},
        "app.composition.idea_spread": {"IDEA_SPREAD": False},
        "app.motion.resolution": {"IDEA_CLIMAX_WASH": False},
        "app.boundary.release": {"IDEA_BOARD": False},
    },
    2: {
        "app.composition.focus_staging": {"FOCUS_STAGING": False},
        "app.composition.idea_spread": {"IDEA_SPREAD": False},
        "app.motion.resolution": {"IDEA_CLIMAX_WASH": False},
        "app.boundary.release": {"IDEA_BOARD": False, "SCENE_WHIP": False},
    },
}

# Failures no safer edit can fix: the inputs or the machine are the problem.
NOT_RECOVERABLE = frozenset({
    "EXPORT_ROOT_UNAVAILABLE",
    "WORK_ROOT_INSUFFICIENT_SPACE",
    "EXPORT_ROOT_INSUFFICIENT_SPACE",
    "WORKSPACE_NOT_WRITABLE",
    "OUTPUT_ROOT_NOT_WRITABLE",
    "TARGET_SET_INVALID",
    "ASSET_BAD_CUTOUT",
})


def recoverable(error: BaseException) -> bool:
    """Planning failures climb the ladder: a typed stage failure (unless the inputs or the
    machine are the problem) and an unexpected planning error alike, since a safer level
    may not reach the code that failed. Cancellation, a missing dependency and running out
    of memory never do."""
    if not SAFE_LEVELS or isinstance(error, (GenerationCancelledError, DependencyUnavailableError, MemoryError)):
        return False
    if isinstance(error, StageFailedError):
        return error.effective_code not in NOT_RECOVERABLE
    return isinstance(error, Exception)


@contextlib.contextmanager
def safe_level(level: int) -> Iterator[None]:
    """Switch the layers of ``level`` off for the duration of the block (0 = unchanged)."""
    saved: list[tuple[object, str, object]] = []
    try:
        for module_name, values in LEVELS.get(level, {}).items():
            module = importlib.import_module(module_name)
            for name, value in values.items():
                saved.append((module, name, getattr(module, name)))
                setattr(module, name, value)
        yield
    finally:
        for module, name, value in reversed(saved):
            setattr(module, name, value)
