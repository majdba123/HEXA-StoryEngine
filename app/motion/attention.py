"""One emphasis owner per instant when motion peaks coincide (Visual Polish VP2-B).

The cohort attention budget groups assets by Story reveal instant. Assets revealed at
different instants can still reach their motion peak together (different durations), and
then two visual units emphasise at once. This pass only looks at actual peak times: when
peaks of different visual units fall within the beat's rhythm accent gap and existing
semantic authority clearly ranks them (RESULT > PRIMARY > other), the subordinate peak is
softened to the existing participant gain — never below the shared readability floor.
Equal authority, missing authority, already-arbitrated cohort members and geometry-locked
family members are left untouched. Timing, settle and final Composition never change.
"""
from __future__ import annotations

from math import hypot

from app.models import LayoutItem, MotionCue
from app.motion.timing import (
    projected_motion_activity_px,
    semantic_readability_floor,
    semantic_readability_floor_px,
)

SUBORDINATE_GAIN = 0.58  # the existing cohort "participant" gain
_ARBITRATED_ROLES = {"participant", "secondary", "quiet", "result_peer", "leader_member"}
_EMPHASIS_PHASES = {"ENTRY", "ESTABLISH", "INTERACT", "REACT", "PAYOFF"}
_SEMANTIC_ACCENTS = {"INTERACT", "REACT", "PAYOFF"}


def _focus(cue: MotionCue) -> dict:
    focus = cue.params.get("semantic_focus") if isinstance(cue.params, dict) else None
    return focus if isinstance(focus, dict) else {}


def _tier(cue: MotionCue) -> int:
    focus = _focus(cue)
    values = {str(focus.get(key) or "").upper() for key in ("visual_focus", "role", "semantic_role")}
    if "RESULT" in values:
        return 2
    if str(focus.get("visual_focus") or "").upper() == "PRIMARY":
        return 1
    return 0


def _unit(cue: MotionCue) -> str:
    continuity = cue.params.get("semantic_continuity") if isinstance(cue.params, dict) else None
    unit = continuity.get("semantic_unit_id") if isinstance(continuity, dict) else None
    return str(unit or cue.asset_id)


def _gap(cue: MotionCue) -> float:
    rhythm = _focus(cue).get("rhythm")
    value = rhythm.get("accent_gap_ms") if isinstance(rhythm, dict) else None
    return float(value) / 1000 if isinstance(value, (int, float)) and value > 0 else 0.0


def _programs(cue: MotionCue) -> list[tuple[str | int, str, float, float, dict]]:
    """(key, phase, start, end, program) for every emphasis program of the cue."""
    if cue.segments:
        return [(index, row.phase, float(row.start), float(row.end), row.program)
                for index, row in enumerate(cue.segments) if row.phase in _EMPHASIS_PHASES]
    program = cue.params.get("program") if isinstance(cue.params, dict) else None
    if isinstance(program, dict):
        return [("program", "ENTRY", float(cue.start), float(cue.end), program)]
    return []


def _activity(program: dict, extent: float) -> tuple[float, float]:
    """(normalized activity, peak progress) with the encoded-QA measure."""
    best, progress = 0.0, 0.5
    for frame in program.get("keyframes") or []:
        value = max(hypot(float(frame.get("dx", 0.0)), float(frame.get("dy", 0.0))),
                    abs(float(frame.get("scale", 1.0)) - 1.0) * extent)
        if value > best:
            best, progress = value, float(frame.get("progress", 0.5))
    return best, progress


def _minimum_gain(phase: str, program: dict, item: LayoutItem, duration: float, activity: float) -> float:
    """Smallest gain that keeps the segment on the readability floor, measured exactly as
    encoded QA measures it: accent phases in Composition units, the others in projected pixels."""
    if phase in _SEMANTIC_ACCENTS:
        floor = semantic_readability_floor(phase, item_width=item.width, item_height=item.height,
                                           duration=duration)
        return floor / activity
    peak_px = max((projected_motion_activity_px(
        dx=float(frame.get("dx", 0.0)), dy=float(frame.get("dy", 0.0)), scale=float(frame.get("scale", 1.0)),
        item_width=item.width, item_height=item.height) for frame in program.get("keyframes") or []), default=0.0)
    floor_px = semantic_readability_floor_px(phase, item_width=item.width, item_height=item.height,
                                             duration=duration)
    return floor_px / peak_px if peak_px > 1e-9 else 1.0


def arbitrate_simultaneous_peaks(cues: list[MotionCue], *, items: dict[str, LayoutItem]) -> list[MotionCue]:
    peaks = []
    for position, cue in enumerate(cues):
        item = items.get(cue.asset_id)
        constraints = cue.params.get("render_constraints", {}) if isinstance(cue.params, dict) else {}
        if item is None or constraints.get("geometry_lock"):
            continue
        extent = max(1e-6, min(item.width, item.height))
        for key, phase, start, end, program in _programs(cue):
            activity, progress = _activity(program, extent)
            if activity > 1e-9 and end > start:
                peaks.append({"position": position, "key": key, "phase": phase, "start": start, "end": end,
                              "time": start + (end - start) * progress, "activity": activity,
                              "tier": _tier(cue), "unit": _unit(cue), "gap": _gap(cue), "item": item,
                              "program": program})
    peaks.sort(key=lambda row: (row["time"], row["position"], str(row["key"])))
    softened: dict[tuple[int, str | int], tuple[float, str]] = {}
    for index, left in enumerate(peaks):
        for right in peaks[index + 1:]:
            gap = max(left["gap"], right["gap"])
            if right["time"] - left["time"] > gap:
                break
            if left["unit"] == right["unit"] or left["tier"] == right["tier"] or gap <= 0.0:
                continue
            low, high = (left, right) if left["tier"] < right["tier"] else (right, left)
            cue = cues[low["position"]]
            if str(_focus(cue).get("cohort_role") or "") in _ARBITRATED_ROLES:
                continue
            keep = _minimum_gain(low["phase"], low["program"], low["item"], low["end"] - low["start"],
                                 low["activity"])
            gain = max(SUBORDINATE_GAIN, min(1.0, keep * 1.02))
            if gain < 1.0:
                softened[(low["position"], low["key"])] = (gain, cues[high["position"]].asset_id)
    if not softened:
        return cues
    output = list(cues)
    for (position, key), (gain, leader) in sorted(softened.items(), key=lambda row: (row[0][0], str(row[0][1]))):
        cue = output[position]

        def scaled(program: dict) -> dict:
            frames = [{**frame, "dx": float(frame.get("dx", 0.0)) * gain, "dy": float(frame.get("dy", 0.0)) * gain,
                       "scale": 1.0 + (float(frame.get("scale", 1.0)) - 1.0) * gain}
                      for frame in program.get("keyframes") or []]
            return {**program, "keyframes": frames}

        params = dict(cue.params)
        notes = list(params.get("attention_arbitration") or [])
        if key == "program":
            params["program"] = scaled(params["program"])
            notes.append({"phase": "ENTRY", "yielded_to": leader, "gain": round(gain, 4)})
            output[position] = cue.model_copy(update={"params": {**params, "attention_arbitration": notes}})
        else:
            segments = list(cue.segments)
            segments[key] = segments[key].model_copy(update={"program": scaled(segments[key].program)})
            notes.append({"phase": segments[key].phase, "yielded_to": leader, "gain": round(gain, 4)})
            output[position] = cue.model_copy(update={"segments": segments,
                                                      "params": {**params, "attention_arbitration": notes}})
    return output
