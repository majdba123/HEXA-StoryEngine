"""An entering asset arrives at entry speed, not across its whole Story window.

Story owns when an asset reveals and when its meaning settles. When that window is long
(an opening carrier established from the scene's first word, or a long spoken phrase),
the entry program used to be stretched across all of it: a sub-pixel creep for one to
two seconds, then a two-frame snap on the spoken word. The approved references never
creep; an entry ramps in a few frames and the asset then rests.

This pass keeps every Story instant and only redistributes an entry's own keyframes:

* ARRIVAL shape (start pose -> rest pose): the approach finishes within the ENTRY
  comfort target, or the shortest frame-grid duration the ENTRY comfort speed allows,
  and the asset rests until the cue ends.
* PEAK shape (start pose -> accent -> rest, the accent placed on Story's semantic
  peak): the asset arrives at rest the same way, holds, and performs the authored
  accent around the unchanged peak instant, rising as fast as it falls.
* An opacity ramp longer than the measured reference ramps (13 frames) ends with the
  arrival instead.

Never touched: hero travel, geometry-locked or compound families, static programs,
semantic segments other than ENTRY, cue windows, Story settle/peak params.
"""
from __future__ import annotations

from math import ceil, hypot

from app.models import CompositionBeat, LayoutItem, MotionCue
from app.motion.timing import motion_comfort

_EPS = 1e-6
_FRAME = 1 / 30
# Measured reference entries ramp opacity over 3-13 frames (Sprint 4.4 reference study).
REFERENCE_MAX_OPACITY_RAMP = 13 / 30


def _pose(frame: dict) -> tuple[float, float, float]:
    return float(frame.get("dx", 0.0)), float(frame.get("dy", 0.0)), float(frame.get("scale", 1.0))


def _is_rest(frame: dict) -> bool:
    dx, dy, scale = _pose(frame)
    return abs(dx) <= 1e-9 and abs(dy) <= 1e-9 and abs(scale - 1.0) <= 1e-9


def _peak_leg_speed(frames: list[dict], duration: float, item: LayoutItem) -> float:
    """Fastest keyframe leg, in the units encoded QA uses for MOTION_TOO_FAST."""
    extent = max(1e-6, min(float(item.width), float(item.height)))
    rows = sorted(frames, key=lambda row: float(row.get("progress", 0.0)))
    speed = 0.0
    for left, right in zip(rows, rows[1:]):
        seconds = max(1e-6, (float(right["progress"]) - float(left["progress"])) * duration)
        (lx, ly, ls), (rx, ry, rs) = _pose(left), _pose(right)
        speed = max(speed, max(hypot(rx - lx, ry - ly), abs(rs - ls) * extent) / seconds)
    return speed


def bounded_entry(frames: list[dict], duration: float, item: LayoutItem) -> tuple[list[dict], dict] | None:
    """Return (keyframes, audit) with the approach bounded, or None when unchanged."""
    if duration <= 0 or len(frames) < 2:
        return None
    rows = sorted((dict(row) for row in frames), key=lambda row: float(row.get("progress", 0.0)))
    if _is_rest(rows[0]) or abs(float(rows[0].get("progress", 0.0))) > 1e-9:
        return None  # nothing approaches from a start pose
    # The approach ends at the first rest keyframe (ARRIVAL) or at the first positive
    # scale accent reached from below (PEAK).
    end = None
    shape = None
    for index in range(1, len(rows)):
        if _is_rest(rows[index]):
            end, shape = index, "ARRIVAL"
            break
        if _pose(rows[index])[2] > 1.0 + 1e-9 and _pose(rows[index - 1])[2] <= 1.0 + 1e-9:
            end, shape = index, "PEAK"
            break
    if end is None:
        return None
    approach = float(rows[end]["progress"]) * duration
    profile = motion_comfort("ENTRY")
    target = ceil(profile.target_seconds / _FRAME - _EPS) * _FRAME
    if approach <= target + _FRAME + _EPS:
        return None

    def compressed(seconds: float) -> list[dict] | None:
        if shape == "ARRIVAL":
            scale = seconds / approach
            out = [{**row, "progress": float(row["progress"]) * scale} if i <= end else row
                   for i, row in enumerate(rows)]
            if end == len(rows) - 1:
                out.append({**rows[end], "progress": 1.0})  # the asset rests to the cue end
            return out
        # PEAK: start pose -> rest within ``seconds``; rest; accent around the peak.
        peak = rows[end]
        peak_p = float(peak["progress"])
        fall = (1.0 - peak_p) * duration
        rise = min(max(2 * _FRAME, fall), 0.2)
        rest_until = peak_p - rise / duration
        if rest_until * duration < seconds + _FRAME - _EPS:
            return None
        start = rows[0]
        rest = {"progress": seconds / duration, "dx": 0.0, "dy": 0.0, "scale": 1.0,
                "easing": start.get("easing", "ease_out_cubic")}
        hold = {"progress": rest_until, "dx": 0.0, "dy": 0.0, "scale": 1.0,
                "easing": peak.get("easing", "ease_out_cubic")}
        return [start, rest, hold, *rows[end:]]

    seconds = target
    while seconds < approach - _EPS:
        candidate = compressed(seconds)
        if candidate is None:
            return None
        if _peak_leg_speed(candidate, duration, item) <= profile.max_normalized_speed + 1e-9:
            return candidate, {"shape": shape, "approach_from": round(approach, 4),
                               "approach_to": round(seconds, 4)}
        seconds += _FRAME
    return None


class EntryArrivalPolicy:
    """Bound every entry's approach to entry speed; Story windows are unchanged."""

    def apply(self, cues: list[MotionCue], *, composition: list[CompositionBeat]) -> list[MotionCue]:
        layouts = {(beat.beat_id, item.asset_id): item for beat in composition for item in beat.items}
        output = list(cues)
        for position, cue in enumerate(cues):
            item = layouts.get((cue.beat_id, cue.asset_id))
            params = cue.params if isinstance(cue.params, dict) else {}
            if item is None or params.get("hero_travel"):
                continue
            if (params.get("render_constraints") or {}).get("geometry_lock"):
                continue  # family members share one authored clock
            program = params.get("program") or {}
            if "compound_unit" in str(program.get("name") or "") or "family" in str(program.get("name") or ""):
                continue
            audit: dict = {}
            update: dict = {}
            entry_index = next((i for i, row in enumerate(cue.segments) if row.phase == "ENTRY"), None)
            if entry_index is not None:
                segment = cue.segments[entry_index]
                result = bounded_entry(list((segment.program or {}).get("keyframes") or []),
                                       float(segment.end) - float(segment.start), item)
                if result is not None:
                    frames, audit = result
                    segments = list(cue.segments)
                    segments[entry_index] = segment.model_copy(
                        update={"program": {**segment.program, "keyframes": frames}})
                    update["segments"] = segments
                    audit["target"] = "ENTRY_segment"
                    arrival = float(segment.start) + audit["approach_to"]
            elif not cue.segments and program:
                result = bounded_entry(list(program.get("keyframes") or []), float(cue.end) - float(cue.start), item)
                if result is not None:
                    frames, audit = result
                    params = {**params, "program": {**program, "keyframes": frames}}
                    audit["target"] = "base_program"
                    arrival = float(cue.start) + audit["approach_to"]
            if not audit:
                continue
            ramp = params.get("entry_opacity")
            if isinstance(ramp, dict):
                limit = float(ramp["start"]) + max(REFERENCE_MAX_OPACITY_RAMP, arrival - float(ramp["start"]))
                if float(ramp["settle"]) > limit + _EPS:
                    params = {**params, "entry_opacity": {**ramp, "settle": limit}}
                    audit["opacity_settle"] = round(limit, 4)
            params = {**params, "entry_arrival": audit}
            update["params"] = params
            output[position] = cue.model_copy(update=update)
        return output
