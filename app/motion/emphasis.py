from __future__ import annotations

from typing import Any

from app.models import LayoutItem, MotionCue, MotionSegment
from app.reference.profile import HexaVisualProfile

from .collision import authored_overlap_ratio, box, overlap_ratio
from .timing import motion_comfort, semantic_readability_floor_px

# A character the semantic event is about may grow briefly after its reveal settles and
# return to Composition geometry before the next semantic reveal. The segment starts and
# ends at identity (scale 1.0, dx = dy = 0), so settled geometry is never Motion-owned.
CHARACTER_EMPHASIS_MAX_DELTA = 0.12
CHARACTER_EMPHASIS_MIN_DELTA = 0.05
CHARACTER_EMPHASIS_MIN_SECONDS = 0.30
CHARACTER_EMPHASIS_MAX_SECONDS = 0.60
_PEAK_PROGRESS = 0.45
_OVERLAP_SLACK = 0.005
_SAFETY = 0.95
_EPS = 1e-6


def apply_character_emphasis(
    cue: MotionCue,
    *,
    item: LayoutItem,
    layout_items: list[LayoutItem],
    bound: float,
    semantic_event_id: str | None,
    entry_segment: MotionSegment | None = None,
) -> MotionCue:
    """Add one comfort-bounded emphasis to the character's own reveal window, or abstain.

    ``bound`` is the next Story-owned semantic reveal (or beat end): the emphasis ends
    before it. Any failed bound (window, comfort speed, safe frame, overlaps, collisions
    with the cue's own later segments) means no emphasis.
    """
    existing_entry = next((row for row in cue.segments if row.phase == "ENTRY"), None)
    entry = existing_entry or entry_segment
    if entry is None:
        return _audit(cue, applied=False, reason="no_entry_program")
    # A static reveal has nothing to protect: the emphasis then begins with the reveal
    # itself and replaces the static ENTRY. A moving ENTRY keeps its own window, and the
    # emphasis starts once it has settled.
    merge_static_entry = _is_static(entry.program)
    start = float(cue.start) if merge_static_entry else float(cue.end)
    later = [
        float(segment.start) for segment in cue.segments
        if segment.phase != "ENTRY" and float(segment.start) >= start - _EPS
    ]
    end = min(float(bound), *later) if later else float(bound)
    end = min(end, start + CHARACTER_EMPHASIS_MAX_SECONDS)
    duration = end - start
    if duration < CHARACTER_EMPHASIS_MIN_SECONDS - _EPS:
        return _audit(cue, applied=False, reason="no_free_window", free_seconds=duration)
    if any(
        float(segment.start) < end - _EPS and float(segment.end) > start + _EPS
        for segment in cue.segments
        if segment.phase != "ENTRY"
    ):
        return _audit(cue, applied=False, reason="overlaps_semantic_segment")

    planned = _plan_scale(duration=duration, item=item, layout_items=layout_items)
    if planned is None:
        return _audit(
            cue, applied=False, reason="no_safe_headroom", free_seconds=duration,
            window=(start, end),
        )
    scale, lean_x, lean_y = planned

    segments = [row for row in cue.segments if not (merge_static_entry and row.phase == "ENTRY")]
    if not merge_static_entry and existing_entry is None:
        # Once any segment exists the renderer evaluates segments only, so a moving base
        # ENTRY must be carried as a segment (prepared by the planner).
        segments.insert(0, entry)
    segments.append(MotionSegment(
        phase="ESTABLISH",
        start=start,
        end=end,
        program=_program(scale, lean_x, lean_y),
        semantic_event_id=semantic_event_id,
        semantic_action="EMPHASIZE",
        involvement="FOCUS",
        handoff_deadline=end,
    ))
    segments.sort(key=lambda segment: (float(segment.start), float(segment.end)))
    params = dict(cue.params)
    params["character_emphasis"] = {
        "applied": True,
        "peak_scale": round(scale, 4),
        "lean": [round(lean_x, 4), round(lean_y, 4)],
        "start": round(start, 4),
        "end": round(end, 4),
    }
    return cue.model_copy(update={"params": params, "segments": segments})


def _is_static(program: dict[str, Any]) -> bool:
    frames = program.get("keyframes")
    if not isinstance(frames, list) or len(frames) < 2:
        return False
    return all(
        abs(float(f.get("dx", 0.0))) <= _EPS and abs(float(f.get("dy", 0.0))) <= _EPS
        and abs(float(f.get("scale", 1.0)) - 1.0) <= _EPS
        for f in frames
    )


def _audit(
    cue: MotionCue, *, applied: bool, reason: str, free_seconds: float | None = None,
    window: tuple[float, float] | None = None,
) -> MotionCue:
    params = dict(cue.params)
    params["character_emphasis"] = {"applied": applied, "reason": reason}
    if free_seconds is not None:
        params["character_emphasis"]["free_seconds"] = round(max(0.0, free_seconds), 3)
    if window is not None:
        params["character_emphasis"]["window"] = [round(window[0], 4), round(window[1], 4)]
    return cue.model_copy(update={"params": params})


def _program(scale: float, dx: float = 0.0, dy: float = 0.0) -> dict[str, Any]:
    return {
        "name": "character_emphasis",
        "settle_progress": 1.0,
        "keyframes": [
            {"progress": 0.0, "dx": 0.0, "dy": 0.0, "scale": 1.0, "easing": "ease_in_out_cubic"},
            {"progress": _PEAK_PROGRESS, "dx": dx, "dy": dy, "scale": scale,
             "easing": "ease_in_out_cubic"},
            {"progress": 1.0, "dx": 0.0, "dy": 0.0, "scale": 1.0, "easing": "smoothstep"},
        ],
    }


def _fit(
    item: LayoutItem, others: list[LayoutItem], *, scale: float
) -> tuple[float, float] | None:
    """Smallest lean-in offset keeping the grown box in the safe frame, or None.

    Growth that would cross a safe margin is shifted back inside by the overflow (never
    more); the offset is temporary and zero again at settle. Overlaps with neighbours may
    not exceed what Composition already authored.
    """
    profile = HexaVisualProfile.production()
    left, top, right, bottom = box(item, (0.0, 0.0, scale))
    dx = dy = 0.0
    if left < profile.safe_left:
        dx = profile.safe_left - left
    elif right > profile.safe_right:
        dx = profile.safe_right - right
    if top < profile.safe_top:
        dy = profile.safe_top - top
    elif bottom > profile.safe_bottom:
        dy = profile.safe_bottom - bottom
    grown = box(item, (dx, dy, scale))
    if (
        grown[0] < profile.safe_left - _EPS or grown[2] > profile.safe_right + _EPS
        or grown[1] < profile.safe_top - _EPS or grown[3] > profile.safe_bottom + _EPS
    ):
        return None
    for other in others:
        if other.asset_id == item.asset_id:
            continue
        allowed = authored_overlap_ratio(item, other) + _OVERLAP_SLACK
        if overlap_ratio(grown, box(other, (0.0, 0.0, 1.0))) > allowed:
            return None
    return dx, dy


def _plan_scale(
    *, duration: float, item: LayoutItem, layout_items: list[LayoutItem]
) -> tuple[float, float, float] | None:
    extent = max(1e-6, min(item.width, item.height))
    limit = motion_comfort("ESTABLISH").max_normalized_speed * _SAFETY
    shortest_leg = min(_PEAK_PROGRESS, 1.0 - _PEAK_PROGRESS) * duration

    def offsets(delta: float) -> tuple[float, float] | None:
        fitted = _fit(item, layout_items, scale=1.0 + delta)
        if fitted is None:
            return None
        move = (fitted[0] ** 2 + fitted[1] ** 2) ** 0.5
        if max(delta * extent, move) / max(shortest_leg, _EPS) > limit:
            return None
        return fitted

    low, high = CHARACTER_EMPHASIS_MIN_DELTA, CHARACTER_EMPHASIS_MAX_DELTA
    if offsets(low) is None:
        return None
    # Feasibility is monotonic in delta: bisect to the largest safe peak.
    for _ in range(12):
        middle = (low + high) / 2.0
        if offsets(middle) is not None:
            low = middle
        else:
            high = middle
    dx, dy = offsets(low) or (0.0, 0.0)
    return 1.0 + low, dx, dy


# --- Supporting-element de-emphasis ---------------------------------------------------------------
# A focused character that cannot grow inside the safe frame keeps its Composition
# geometry while the settled supporting elements briefly recede. Receding is a scale dip
# that starts and ends on Composition geometry, so the focus reads without any element
# leaving its authored place.
SUPPORT_DIP_MIN_DELTA = 0.07
SUPPORT_DIP_MAX_DELTA = 0.10
SUPPORT_DIP_MAX_ELEMENTS = 4


def deemphasize_supporting(
    cues: list[MotionCue],
    *,
    focus_asset_id: str,
    layout_items: list[LayoutItem],
    protected_asset_ids: set[str],
    semantic_event_id: str | None,
    carry_entry,
) -> list[MotionCue]:
    """Recede the settled supporting elements during a focus window, or abstain.

    Eligible elements are visible and settled at the window start, are not characters,
    have no semantic segment inside the window and can dip by the encoded-readable
    minimum within comfort speed. Any ineligible element simply keeps its geometry. If
    nothing is eligible, or more than a restrained handful would move, nothing changes.
    """
    by_asset = {cue.asset_id: cue for cue in cues}
    focus = by_asset.get(focus_asset_id)
    audit = (focus.params.get("character_emphasis") if focus is not None else None) or {}
    if (
        focus is None
        or audit.get("applied")
        or audit.get("reason") != "no_safe_headroom"
        or not audit.get("window")
    ):
        return cues
    start, end = (float(value) for value in audit["window"])
    duration = end - start
    items = {item.asset_id: item for item in layout_items}
    plans: dict[str, float] = {}
    for cue in cues:
        item = items.get(cue.asset_id)
        if (
            item is None or cue.asset_id == focus_asset_id
            or cue.asset_id in protected_asset_ids
            or float(cue.start) > start + _EPS
        ):
            continue
        entry = next((row for row in cue.segments if row.phase == "ENTRY"), None)
        entry_program = entry.program if entry is not None else cue.params.get("program") or {}
        if float(cue.end) > start + _EPS and not _is_static(entry_program):
            continue  # still arriving: its own entry owns the moment
        if any(
            row.phase != "ENTRY"
            and float(row.start) < end - _EPS and float(row.end) > start + _EPS
            for row in cue.segments
        ):
            continue  # expressing its own semantic phase
        delta = _dip_delta(item, duration)
        if delta is not None:
            plans[cue.asset_id] = delta
    if not plans or len(plans) > SUPPORT_DIP_MAX_ELEMENTS:
        reason = "no_eligible_support" if not plans else "too_many_supporting"
        return _mark_focus(cues, focus_asset_id, {"applied": False, "reason": reason})

    output: list[MotionCue] = []
    dipped: list[str] = []
    for cue in cues:
        delta = plans.get(cue.asset_id)
        if delta is None:
            output.append(cue)
            continue
        segments = list(cue.segments)
        if not any(row.phase == "ENTRY" for row in segments):
            carried = carry_entry(cue, item=items[cue.asset_id])
            if carried is None:
                output.append(cue)
                continue
            segments.insert(0, carried)
        segments.append(MotionSegment(
            phase="ESTABLISH", start=start, end=end,
            program=_dip_program(delta),
            semantic_event_id=semantic_event_id,
            semantic_action="DEEMPHASIZE",
            involvement="SUPPORT",
            handoff_deadline=end,
        ))
        segments.sort(key=lambda row: (float(row.start), float(row.end)))
        params = dict(cue.params)
        params["supporting_deemphasis"] = {
            "applied": True, "dip": round(delta, 4), "focus_asset_id": focus_asset_id,
            "start": round(start, 4), "end": round(end, 4),
        }
        output.append(cue.model_copy(update={"params": params, "segments": segments}))
        dipped.append(cue.asset_id)
    return _mark_focus(output, focus_asset_id, {
        "applied": bool(dipped), "assets": sorted(dipped),
        "start": round(start, 4), "end": round(end, 4),
    })


def _mark_focus(cues: list[MotionCue], focus_asset_id: str, audit: dict[str, Any]) -> list[MotionCue]:
    output = list(cues)
    for index, cue in enumerate(output):
        if cue.asset_id == focus_asset_id:
            params = dict(cue.params)
            params["supporting_deemphasis"] = audit
            output[index] = cue.model_copy(update={"params": params})
    return output


def _dip_delta(item: LayoutItem, duration: float) -> float | None:
    """Smallest dip that clears the encoded readability floor, inside comfort speed."""
    asset_px = max(1.0, min(1920.0 * item.width, 1080.0 * item.height))
    floor_px = semantic_readability_floor_px(
        "ESTABLISH", item_width=item.width, item_height=item.height, duration=duration,
    )
    delta = max(SUPPORT_DIP_MIN_DELTA, floor_px * 1.15 / asset_px)
    if delta > SUPPORT_DIP_MAX_DELTA:
        return None
    extent = max(1e-6, min(item.width, item.height))
    limit = motion_comfort("ESTABLISH").max_normalized_speed * _SAFETY
    leg = min(_PEAK_PROGRESS, 1.0 - _PEAK_PROGRESS) * duration
    if delta * extent / max(leg, _EPS) > limit:
        return None
    return delta


def _dip_program(delta: float) -> dict[str, Any]:
    return {
        "name": "supporting_deemphasis",
        "settle_progress": 1.0,
        "keyframes": [
            {"progress": 0.0, "dx": 0.0, "dy": 0.0, "scale": 1.0, "easing": "ease_in_out_cubic"},
            {"progress": _PEAK_PROGRESS, "dx": 0.0, "dy": 0.0, "scale": 1.0 - delta,
             "easing": "ease_in_out_cubic"},
            {"progress": 1.0, "dx": 0.0, "dy": 0.0, "scale": 1.0, "easing": "smoothstep"},
        ],
    }
