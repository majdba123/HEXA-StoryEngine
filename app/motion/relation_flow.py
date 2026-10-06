from __future__ import annotations

from math import hypot
from typing import Any, Callable

from app.choreography import RelationFlowDecision, RelationTreatment
from app.models import LayoutItem, MotionCue, MotionSegment, StoryBeat
from app.targets import active_target, frame_size

from .collision import authored_overlap_ratio, box, overlap_ratio
from .emphasis import (
    CHARACTER_EMPHASIS_MAX_SECONDS,
    CHARACTER_EMPHASIS_MIN_SECONDS,
    _PEAK_PROGRESS,
    _SAFETY,
    _dip_delta,
    _is_static,
    reference_dip_delta,
)
from .timing import motion_comfort

# The previous leader yields toward the new one: a readable recede with a small lean
# toward the target, starting and ending on Composition geometry.
HANDOFF_LEAN_MAX_PX = 28.0
_OVERLAP_SLACK = 0.005
_EPS = 1e-6


def apply_relation_focus_handoffs(
    cues: list[MotionCue],
    *,
    beat: StoryBeat,
    decisions: tuple[RelationFlowDecision, ...],
    layout_items: list[LayoutItem],
    next_reveal: Callable[[MotionCue], float],
    carry_entry,
    reference_applied: Callable[[str, str], bool | None] | None = None,
) -> list[MotionCue]:
    """Execute Choreography FOCUS_HANDOFF decisions, or abstain per relation.

    At the target's own Story reveal (never earlier) the authored source recedes and leans
    toward the target, then returns to identity before the next Story reveal. Abstains
    when the source is still arriving or expressing another semantic phase, when the
    window is too short, when the recede cannot be read, or when the source is one piece
    of a split semantic carrier.
    """
    handoffs = [row for row in decisions if row.treatment == RelationTreatment.FOCUS_HANDOFF]
    if not handoffs:
        return cues
    output = list(cues)
    index = {cue.asset_id: position for position, cue in enumerate(output)}
    items = {item.asset_id: item for item in layout_items}
    unit_by_asset = {
        row.asset_id: row.semantic_unit_id for row in beat.asset_activations
    }
    for decision in sorted(
        handoffs, key=lambda row: (row.target_asset_id or "", row.source_asset_id or ""),
    ):
        source_id, target_id = decision.source_asset_id, decision.target_asset_id
        if source_id not in index or target_id not in index or source_id not in items:
            continue
        source = output[index[source_id]]
        target = output[index[target_id]]
        forced = reference_applied(source_id, target_id) if reference_applied else None
        reason, plan = _plan(
            source=source, target=target, beat=beat, items=items,
            layout_items=layout_items, unit_by_asset=unit_by_asset,
            next_reveal=next_reveal(target), force_readable=forced is True,
        )
        if forced is False and plan is not None:
            reason, plan = "reference_target_abstained", None
        audit: dict[str, Any] = {
            "relationship": decision.relationship,
            "target_asset_id": target_id,
            "applied": plan is not None,
        }
        if plan is None:
            audit["reason"] = reason
            output[index[source_id]] = _audit(source, audit)
            continue
        start, end, delta, dx, dy = plan
        segments = list(source.segments)
        if not any(row.phase == "ENTRY" for row in segments):
            carried = carry_entry(source, item=items[source_id])
            if carried is None:
                audit.update(applied=False, reason="no_entry_program")
                output[index[source_id]] = _audit(source, audit)
                continue
            segments.insert(0, carried)
        segments.append(MotionSegment(
            phase="ESTABLISH", start=start, end=end,
            program=_program(delta, dx, dy),
            semantic_event_id=decision.target_event_id,
            semantic_action="FOCUS_HANDOFF",
            relationship=decision.relationship,
            involvement="SUPPORT",
            source_asset_id=source_id,
            target_asset_id=target_id,
            handoff_deadline=end,
        ))
        segments.sort(key=lambda row: (float(row.start), float(row.end)))
        audit.update(
            dip=round(delta, 4), lean=[round(dx, 4), round(dy, 4)],
            start=round(start, 4), end=round(end, 4),
        )
        output[index[source_id]] = _audit(
            source.model_copy(update={"segments": segments}), audit,
        )
    return output


def _plan(
    *,
    source: MotionCue,
    target: MotionCue,
    beat: StoryBeat,
    items: dict[str, LayoutItem],
    layout_items: list[LayoutItem],
    unit_by_asset: dict[str, str | None],
    next_reveal: float,
    force_readable: bool = False,
) -> tuple[str, tuple[float, float, float, float, float] | None]:
    source_id = source.asset_id
    unit = unit_by_asset.get(source_id)
    if any(
        other != source_id and (other.startswith(f"{source_id}:") or (unit and value == unit))
        for other, value in unit_by_asset.items()
    ):
        return "split_semantic_carrier", None
    start = float(target.start)
    if float(source.start) > start - _EPS:
        return "source_not_revealed", None
    entry = next((row for row in source.segments if row.phase == "ENTRY"), None)
    entry_program = entry.program if entry is not None else source.params.get("program") or {}
    if float(source.end) > start + _EPS and not _is_static(entry_program):
        return "source_still_arriving", None
    end = min(float(next_reveal), float(beat.end), start + CHARACTER_EMPHASIS_MAX_SECONDS)
    for row in source.segments:
        if row.phase == "ENTRY" or float(row.end) <= start + _EPS:
            continue
        if float(row.start) <= start + _EPS:
            return "source_busy", None
        end = min(end, float(row.start))
    duration = end - start
    if duration < CHARACTER_EMPHASIS_MIN_SECONDS - _EPS:
        return "short_window", None
    item = items[source_id]
    delta = _dip_delta(item, duration)
    if delta is None and force_readable:
        # Reference decided: size the recede within this geometry's comfort budget.
        delta = reference_dip_delta(item, duration)
    if delta is None:
        return "unreadable_recede", None
    dx, dy = _lean(item, items.get(target.asset_id), layout_items, delta, duration)
    return "applied", (start, end, delta, dx, dy)


def _lean(
    item: LayoutItem,
    target: LayoutItem | None,
    layout_items: list[LayoutItem],
    delta: float,
    duration: float,
) -> tuple[float, float]:
    """Small lean toward the target, or none when it is unsafe or uncomfortable."""
    if target is None:
        return 0.0, 0.0
    _FRAME = tuple(float(value) for value in frame_size())
    vx = (float(target.x) - float(item.x)) * _FRAME[0]
    vy = (float(target.y) - float(item.y)) * _FRAME[1]
    length = hypot(vx, vy)
    extent_px = min(float(item.width) * _FRAME[0], float(item.height) * _FRAME[1])
    lean_px = min(HANDOFF_LEAN_MAX_PX, 0.5 * delta * extent_px)
    if length < 1.0 or lean_px <= 0.0:
        return 0.0, 0.0
    dx = vx / length * lean_px / _FRAME[0]
    dy = vy / length * lean_px / _FRAME[1]
    limit = motion_comfort("ESTABLISH").max_normalized_speed * _SAFETY
    leg = min(_PEAK_PROGRESS, 1.0 - _PEAK_PROGRESS) * duration
    extent = max(1e-6, min(item.width, item.height))
    if max(delta * extent, hypot(dx, dy)) / max(leg, _EPS) > limit:
        return 0.0, 0.0
    moved = box(item, (dx, dy, 1.0 - delta))
    profile = active_target().safe_zones.content
    if (
        moved[0] < profile.left - _EPS or moved[2] > profile.right + _EPS
        or moved[1] < profile.top - _EPS or moved[3] > profile.bottom + _EPS
    ):
        return 0.0, 0.0
    for other in layout_items:
        if other.asset_id == item.asset_id:
            continue
        allowed = authored_overlap_ratio(item, other) + _OVERLAP_SLACK
        if overlap_ratio(moved, box(other, (0.0, 0.0, 1.0))) > allowed:
            return 0.0, 0.0
    return dx, dy


def _program(delta: float, dx: float, dy: float) -> dict[str, Any]:
    return {
        "name": "relation_focus_handoff",
        "settle_progress": 1.0,
        "keyframes": [
            {"progress": 0.0, "dx": 0.0, "dy": 0.0, "scale": 1.0, "easing": "ease_in_out_cubic"},
            {"progress": _PEAK_PROGRESS, "dx": dx, "dy": dy, "scale": 1.0 - delta,
             "easing": "ease_in_out_cubic"},
            {"progress": 1.0, "dx": 0.0, "dy": 0.0, "scale": 1.0, "easing": "smoothstep"},
        ],
    }


def _audit(cue: MotionCue, entry: dict[str, Any]) -> MotionCue:
    params = dict(cue.params)
    params["relation_flow"] = [*(params.get("relation_flow") or []), entry]
    return cue.model_copy(update={"params": params})
