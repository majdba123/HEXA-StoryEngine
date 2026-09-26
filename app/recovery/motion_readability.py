from __future__ import annotations

from dataclasses import dataclass
from math import hypot
from typing import Iterable

from app.models import LayoutItem, MotionCue, MotionSegment, RenderPlan
from app.motion.timing import semantic_readability_duration, semantic_readability_floor


@dataclass(frozen=True, slots=True)
class MotionReadabilityRepairResult:
    plan: RenderPlan
    repaired_segments: int
    untouched_segments: int


def repair_motion_readability(
    plan: RenderPlan,
    *,
    violations: Iterable[object],
    attempt: int,
    safety_margin: float = 1.04,
) -> MotionReadabilityRepairResult:
    """Repair only semantic segments proven below the shared readability floor.

    This is a bounded recovery path, not a replacement for MotionPlanner. Timing,
    semantic ids, relationships, easing and Composition geometry stay unchanged. Only
    the transform amplitude of an already-authored segment may increase, and only for
    a (beat, asset, phase) tuple explicitly reported by RenderedMotionQA.
    """
    targets = {
        (
            str(getattr(row, "beat_id", "")),
            str(getattr(row, "asset_id", "")),
            str(getattr(row, "phase", "")).upper(),
        )
        for row in violations
        if str(getattr(row, "code", "")) == "MOTION_BELOW_PERCEPTUAL_FLOOR"
    }
    if not targets:
        return MotionReadabilityRepairResult(
            plan=plan,
            repaired_segments=0,
            untouched_segments=0,
        )

    layouts = {
        (beat.beat_id, item.asset_id): item
        for beat in plan.composition
        for item in beat.items
    }
    repaired = 0
    untouched = 0
    motion: list[MotionCue] = []

    for cue in plan.motion:
        item = layouts.get((cue.beat_id, cue.asset_id))
        rows: list[MotionSegment] = []
        for segment in cue.segments:
            target = (cue.beat_id, cue.asset_id, str(segment.phase).upper())
            if item is None or target not in targets:
                rows.append(segment)
                untouched += 1
                continue
            candidate = _repair_segment(
                segment,
                item=item,
                frame_width=plan.width,
                frame_height=plan.height,
                attempt=attempt,
                safety_margin=safety_margin,
            )
            if candidate is segment:
                untouched += 1
            else:
                repaired += 1
            rows.append(candidate)
        motion.append(cue.model_copy(update={"segments": rows}))

    return MotionReadabilityRepairResult(
        plan=plan.model_copy(update={"motion": motion}),
        repaired_segments=repaired,
        untouched_segments=untouched,
    )


def _repair_segment(
    segment: MotionSegment,
    *,
    item: LayoutItem,
    frame_width: int,
    frame_height: int,
    attempt: int,
    safety_margin: float,
) -> MotionSegment:
    program = dict(segment.program)
    if bool(program.get("collision_limited")) or bool(program.get("qa_base_entry")):
        return segment
    if "compound_unit" in str(program.get("name") or ""):
        return segment

    keyframes = program.get("keyframes")
    if not isinstance(keyframes, list) or len(keyframes) < 2:
        return segment

    duration = max(0.0, float(segment.end) - float(segment.start))
    try:
        active_duration = float(program.get("semantic_active_duration", duration))
    except (TypeError, ValueError):
        active_duration = duration
    readability_duration = semantic_readability_duration(
        segment.phase,
        segment_duration=duration,
        active_duration=active_duration,
    )
    floor = semantic_readability_floor(
        segment.phase,
        item_width=item.width,
        item_height=item.height,
        duration=readability_duration,
        frame_width=frame_width,
        frame_height=frame_height,
    )
    if floor <= 0.0:
        return segment

    current = _normalized_activity(
        keyframes,
        item_width=item.width,
        item_height=item.height,
    )
    if current + 1e-9 >= floor:
        return segment

    target = floor * max(1.0, float(safety_margin))
    asset_extent = max(1e-6, min(float(item.width), float(item.height)))
    translation_peak = 0.0
    scale_peak = 0.0
    for frame in keyframes:
        if not isinstance(frame, dict):
            continue
        try:
            translation_peak = max(
                translation_peak,
                hypot(
                    float(frame.get("dx", 0.0)),
                    float(frame.get("dy", 0.0)),
                ),
            )
            scale_peak = max(
                scale_peak,
                abs(float(frame.get("scale", 1.0)) - 1.0) * asset_extent,
            )
        except (TypeError, ValueError):
            continue

    repaired_frames = [dict(frame) for frame in keyframes]
    if translation_peak >= scale_peak and translation_peak > 1e-9:
        gain = target / translation_peak
        for frame in repaired_frames:
            try:
                frame["dx"] = max(
                    -0.075,
                    min(0.075, float(frame.get("dx", 0.0)) * gain),
                )
                frame["dy"] = max(
                    -0.075,
                    min(0.075, float(frame.get("dy", 0.0)) * gain),
                )
            except (TypeError, ValueError):
                continue
    elif scale_peak > 1e-9:
        gain = target / scale_peak
        for frame in repaired_frames:
            try:
                scale = float(frame.get("scale", 1.0))
                frame["scale"] = max(
                    0.90,
                    min(1.14, 1.0 + (scale - 1.0) * gain),
                )
            except (TypeError, ValueError):
                continue
    else:
        peak_index = _semantic_peak_frame_index(repaired_frames, program)
        if peak_index is None:
            return segment
        repaired_frames[peak_index]["dy"] = -min(0.075, target)

    repaired_activity = _normalized_activity(
        repaired_frames,
        item_width=item.width,
        item_height=item.height,
    )
    if repaired_activity + 1e-9 < floor:
        return segment

    program["keyframes"] = repaired_frames
    program["readability_recovery"] = True
    program["readability_recovery_attempt"] = int(attempt)
    program["readability_recovery_previous_activity"] = round(current, 8)
    program["readability_recovery_floor"] = round(floor, 8)
    program["readability_recovery_activity"] = round(repaired_activity, 8)
    return segment.model_copy(update={"program": program})


def _normalized_activity(
    keyframes: list[dict],
    *,
    item_width: float,
    item_height: float,
) -> float:
    asset_extent = max(1e-6, min(float(item_width), float(item_height)))
    best = 0.0
    for frame in keyframes:
        if not isinstance(frame, dict):
            continue
        try:
            translation = hypot(
                float(frame.get("dx", 0.0)),
                float(frame.get("dy", 0.0)),
            )
            scale = abs(float(frame.get("scale", 1.0)) - 1.0) * asset_extent
        except (TypeError, ValueError):
            continue
        best = max(best, translation, scale)
    return best


def _semantic_peak_frame_index(keyframes: list[dict], program: dict) -> int | None:
    try:
        target = float(program.get("semantic_peak_progress", 0.6180339887498949))
    except (TypeError, ValueError):
        target = 0.6180339887498949
    candidates: list[tuple[float, int]] = []
    for index, frame in enumerate(keyframes):
        if not isinstance(frame, dict):
            continue
        try:
            candidates.append(
                (abs(float(frame.get("progress", 0.0)) - target), index)
            )
        except (TypeError, ValueError):
            continue
    if not candidates:
        return None
    return min(candidates)[1]
