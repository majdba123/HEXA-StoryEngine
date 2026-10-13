"""Finish a beat's motion before its final read hold (Visual Polish VP3).

Rhythm owns one minimum read hold per beat. VP2-C reserved it for the base entry window
only; later semantic segments (INTERACT / REACT / PAYOFF accents and FOCUS_HANDOFF
recedes) could still run into the cut, so the final state was never seen at rest. This
pass applies the same rule to every motion segment of the beat:

* only a segment that is still moving inside ``[beat.end - hold, beat.end]`` changes;
* only its end moves earlier; its start (the narration-aligned semantic onset) and the
  keyframe progress shape are unchanged;
* it never becomes shorter than its phase's certified comfort minimum;
* amplitude is reduced only as far as the phase's comfort speed requires (fastest
  keyframe leg, as encoded QA measures it), and the result must stay on the shared
  readability floor; otherwise the segment is left as authored and the conflict recorded;
* a Story semantic-event proxy segment runs on Story's exact window and is never retimed.

A segment that already starts inside the hold cannot be fixed by Motion (its onset is a
Story fact) and is recorded as such. Story, Composition and cue windows never change.
"""
from __future__ import annotations

from math import hypot

from app.models import LayoutItem, MotionCue, StoryBeat
from app.motion.timing import (
    motion_comfort,
    projected_motion_activity_px,
    semantic_readability_floor,
    semantic_readability_floor_px,
)

_SEMANTIC_ACCENTS = {"INTERACT", "REACT", "PAYOFF"}
_EPS = 1e-6


def _activity(program: dict, item: LayoutItem, phase: str) -> float:
    """Peak activity in the unit encoded QA uses for this phase (normalized or pixels)."""
    best = 0.0
    extent = max(1e-6, min(float(item.width), float(item.height)))
    for frame in program.get("keyframes") or []:
        dx, dy = float(frame.get("dx", 0.0)), float(frame.get("dy", 0.0))
        scale = float(frame.get("scale", 1.0))
        if phase in _SEMANTIC_ACCENTS:
            value = max(hypot(dx, dy), abs(scale - 1.0) * extent)
        else:
            value = projected_motion_activity_px(
                dx=dx, dy=dy, scale=scale, item_width=item.width, item_height=item.height)
        best = max(best, value)
    return best


def _normalized_activity(program: dict, item: LayoutItem) -> float:
    extent = max(1e-6, min(float(item.width), float(item.height)))
    return max((max(hypot(float(f.get("dx", 0.0)), float(f.get("dy", 0.0))),
                    abs(float(f.get("scale", 1.0)) - 1.0) * extent)
                for f in program.get("keyframes") or []), default=0.0)


def _peak_leg_speed(program: dict, item: LayoutItem, duration: float) -> float:
    """Fastest keyframe leg, measured exactly as encoded QA measures MOTION_TOO_FAST."""
    extent = max(1e-6, min(float(item.width), float(item.height)))
    rows = sorted((float(f.get("progress", 0.0)), float(f.get("dx", 0.0)), float(f.get("dy", 0.0)),
                   float(f.get("scale", 1.0))) for f in program.get("keyframes") or [])
    speed = 0.0
    for left, right in zip(rows, rows[1:]):
        seconds = max(1e-6, (right[0] - left[0]) * duration)
        speed = max(speed, max(hypot(right[1] - left[1], right[2] - left[2]),
                               abs(right[3] - left[3]) * extent) / seconds)
    return speed


def _floor(phase: str, item: LayoutItem, duration: float) -> float:
    if phase in _SEMANTIC_ACCENTS:
        return semantic_readability_floor(phase, item_width=item.width, item_height=item.height,
                                          duration=duration)
    return semantic_readability_floor_px(phase, item_width=item.width, item_height=item.height,
                                         duration=duration)


def _scaled(program: dict, gain: float) -> dict:
    frames = [{**frame, "dx": float(frame.get("dx", 0.0)) * gain, "dy": float(frame.get("dy", 0.0)) * gain,
               "scale": 1.0 + (float(frame.get("scale", 1.0)) - 1.0) * gain}
              for frame in program.get("keyframes") or []]
    return {**program, "keyframes": frames}


def reserve_scene_read_hold(
    cues: list[MotionCue], *, beat: StoryBeat, hold: float, items: dict[str, LayoutItem],
) -> list[MotionCue]:
    deadline = float(beat.end) - max(0.0, float(hold))
    # A Story semantic-event proxy is executed on Story's exact proxy window: never retime it.
    proxies = {(proxy.asset_id, proxy.semantic_event_id) for proxy in beat.semantic_event_proxies}
    output = list(cues)
    for position, cue in enumerate(cues):
        item = items.get(cue.asset_id)
        if item is None or not cue.segments:
            continue
        constraints = cue.params.get("render_constraints", {}) if isinstance(cue.params, dict) else {}
        if constraints.get("geometry_lock"):
            continue  # family members share one authored footprint clock; never retime one piece
        segments = list(cue.segments)
        notes = []
        for index, segment in enumerate(segments):
            start, end = float(segment.start), float(segment.end)
            if end <= deadline + _EPS:
                continue
            program = segment.program or {}
            if _normalized_activity(program, item) <= 1e-9:
                continue  # a static segment does not move the final state
            if (cue.asset_id, segment.semantic_event_id) in proxies:
                notes.append({"phase": segment.phase, "decision": "story_proxy_window"})
                continue
            if start >= deadline - _EPS:
                notes.append({"phase": segment.phase, "decision": "starts_inside_read_hold",
                              "start": round(start, 4), "deadline": round(deadline, 4)})
                continue
            minimum = min(end - start, motion_comfort(segment.phase).minimum_seconds)
            new_end = max(start + minimum, deadline)
            if new_end >= end - _EPS:
                notes.append({"phase": segment.phase, "decision": "comfort_minimum_reaches_hold",
                              "shortfall_ms": round((new_end - deadline) * 1000)})
                continue
            duration = new_end - start
            speed = _peak_leg_speed(program, item, duration)
            limit = motion_comfort(segment.phase).max_normalized_speed
            gain = min(1.0, limit / speed) if speed > 0 else 1.0
            candidate = _scaled(program, gain) if gain < 1.0 else dict(program)
            if _activity(candidate, item, segment.phase) + 1e-9 < _floor(segment.phase, item, duration):
                notes.append({"phase": segment.phase, "decision": "readability_floor_conflict"})
                continue
            active = candidate.get("semantic_active_duration")
            if isinstance(active, (int, float)) and active > duration:
                candidate["semantic_active_duration"] = duration
            update = {"end": new_end, "program": candidate}
            if segment.handoff_deadline is not None and float(segment.handoff_deadline) > new_end:
                update["handoff_deadline"] = new_end
            segments[index] = segment.model_copy(update=update)
            note = {"phase": segment.phase, "decision": "finished_before_read_hold",
                    "end_from": round(end, 4), "end_to": round(new_end, 4), "amplitude_gain": round(gain, 4)}
            if new_end > deadline + _EPS:
                note.update(decision="shortened_to_comfort_minimum",
                            shortfall_ms=round((new_end - deadline) * 1000))
            notes.append(note)
        if notes:
            params = dict(cue.params)
            params["read_hold"] = notes
            output[position] = cue.model_copy(update={"segments": segments, "params": params})
    return output
