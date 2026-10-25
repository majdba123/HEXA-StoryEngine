"""Remove brief in-place translation reversals from final Motion programs.

These movements read as a shake once encoded: a cutout leaves its settled position by
only a few pixels and returns in a handful of frames. Translation is the only component
changed. Scale accents, arrivals from another position, Story timing and segment meaning
remain owned by their original planners.
"""
from __future__ import annotations

from math import hypot

from app.models import MotionCue


MAX_REVERSAL_SECONDS = 0.4
MAX_REVERSAL_PX = 20.0
REST_TOLERANCE_PX = 0.5


def _without_micro_reversal(program: dict, *, duration: float, width: int, height: int,
                            phase: str) -> dict | None:
    frames = program.get("keyframes")
    if not isinstance(frames, list) or len(frames) < 3 or duration <= 0:
        return None
    try:
        positions = [(float(row.get("dx", 0.0)) * width,
                      float(row.get("dy", 0.0)) * height) for row in frames]
        progress = [float(row["progress"]) for row in frames]
    except (AttributeError, TypeError, ValueError):
        return None
    if any(right <= left for left, right in zip(progress, progress[1:])):
        return None
    activity = max(hypot(x, y) for x, y in positions)
    if not (REST_TOLERANCE_PX < activity <= MAX_REVERSAL_PX):
        return None
    if (hypot(*positions[0]) > REST_TOLERANCE_PX
            or hypot(*positions[-1]) > REST_TOLERANCE_PX):
        return None
    moving = [index for index, (x, y) in enumerate(positions)
              if hypot(x, y) > REST_TOLERANCE_PX]
    first, last = moving[0], moving[-1]
    active_seconds = (progress[last + 1] - progress[first - 1]) * duration
    if active_seconds > MAX_REVERSAL_SECONDS:
        return None
    stable = [{**row, "dx": 0.0, "dy": 0.0} for row in frames]
    result = {**program, "keyframes": stable, "micro_reversal_removed": True}
    if all(abs(float(row.get("scale", 1.0)) - 1.0) <= 1e-9 for row in stable):
        result["name"] = f"reference_still_{phase.lower()}"
        result["stilled_from"] = str(program.get("name") or "")
        result["settle_progress"] = 1.0
    return result


def remove_micro_reversals(motion: list[MotionCue], *, width: int, height: int) -> list[MotionCue]:
    """Apply the final-frame stability rule after all Motion accent authors have run."""
    output: list[MotionCue] = []
    for cue in motion:
        segments = []
        changed = False
        for row in cue.segments:
            program = _without_micro_reversal(
                row.program, duration=float(row.end) - float(row.start), width=width,
                height=height, phase=row.phase)
            segments.append(row.model_copy(update={"program": program}) if program else row)
            changed |= program is not None
        params = cue.params
        if not cue.segments and isinstance(params, dict) and isinstance(params.get("program"), dict):
            program = _without_micro_reversal(
                params["program"], duration=float(cue.end) - float(cue.start), width=width,
                height=height, phase="ENTRY")
            if program is not None:
                params = {**params, "program": program}
                changed = True
        output.append(cue.model_copy(update={"segments": segments, "params": params}) if changed else cue)
    return output
