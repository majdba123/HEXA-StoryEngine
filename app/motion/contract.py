"""Shared, metadata-only motion segment contract.

One implementation of the readability floor and comfort-speed checks that encoded
motion QA applies to a semantic segment. Authoring passes that replace a complete
segment program (for example the PAYOFF icon hit) validate their candidate with the
same functions before committing it, so no pass can hand the renderer a program that
rendered QA is already certain to reject.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from math import hypot

from .hero_travel import HERO_TRAVEL
from .timing import (
    REFERENCE_POP,
    REFERENCE_SLIDE,
    MotionComfortProfile,
    motion_comfort,
    projected_motion_activity_px,
    semantic_readability_duration,
    semantic_readability_floor,
    semantic_readability_floor_px,
)

SEMANTIC_ACCENT_PHASES = frozenset({"INTERACT", "REACT", "PAYOFF"})
# Encoded QA tolerates 8 % keyframe-sampling slack above the comfort ceiling. Authoring
# constructs programs against the bare ceiling; only QA consumes this tolerance.
QA_SPEED_TOLERANCE = 1.08


@dataclass(frozen=True, slots=True)
class SegmentContractViolation:
    code: str
    detail: str
    measured: float
    required: float


def keyframe_activity_normalized(
    keyframes: Sequence[Mapping] | None, *, item_width: float, item_height: float,
) -> float:
    """Peak authored activity in Composition-space units (translation or scale x extent)."""
    if not keyframes:
        return 0.0
    asset_extent = max(1e-6, min(float(item_width), float(item_height)))
    best = 0.0
    for frame in keyframes:
        if not isinstance(frame, Mapping):
            continue
        try:
            translation = hypot(float(frame.get("dx", 0.0)), float(frame.get("dy", 0.0)))
            scale = abs(float(frame.get("scale", 1.0)) - 1.0) * asset_extent
        except (TypeError, ValueError):
            continue
        best = max(best, translation, scale)
    return best


def keyframe_peak_speed_normalized(
    keyframes: Sequence[Mapping] | None, *, duration: float, item_width: float, item_height: float,
) -> float:
    """Peak keyframe-to-keyframe speed in the canonical normalized velocity budget."""
    if not keyframes or len(keyframes) < 2:
        return 0.0
    asset_extent = max(1e-6, min(float(item_width), float(item_height)))
    rows: list[tuple[float, float, float, float]] = []
    for frame in keyframes:
        try:
            rows.append((float(frame.get("progress", 0.0)), float(frame.get("dx", 0.0)),
                         float(frame.get("dy", 0.0)), float(frame.get("scale", 1.0))))
        except (TypeError, ValueError, AttributeError):
            continue
    rows.sort(key=lambda row: row[0])
    peak = 0.0
    for left, right in zip(rows, rows[1:]):
        seconds = max(1e-6, (right[0] - left[0]) * duration)
        translation = hypot(right[1] - left[1], right[2] - left[2])
        scale_motion = abs(right[3] - left[3]) * asset_extent
        peak = max(peak, max(translation, scale_motion) / seconds)
    return peak


def comfort_profile_for(phase: str, *, program_name: str, params: Mapping | None) -> MotionComfortProfile:
    """The comfort ceiling encoded QA applies to this segment (authorized contracts only)."""
    params = params if isinstance(params, Mapping) else {}
    phase = str(phase).upper()
    if phase == "ENTRY" and isinstance(params.get("hero_travel"), Mapping):
        return HERO_TRAVEL
    if (phase in {"ENTRY", "PAYOFF", "REACT"} and isinstance(params.get("reference_pop"), Mapping)
            and program_name.startswith("reference_pop")):
        # A target that reacts with its own reveal arrives as that pop (resolution._pop only
        # gives REACT a pop when it starts with the reveal): an entrance, like its PAYOFF.
        return REFERENCE_POP
    if (phase in {"ENTRY", "PAYOFF", "REACT"} and isinstance(params.get("reference_slide"), Mapping)
            and program_name.startswith("reference_slide")):
        return REFERENCE_SLIDE
    if (phase in {"INTERACT", "REACT"} and isinstance(params.get("relation_approach"), Mapping)
            and program_name.startswith("reference_relation_approach")):
        # A relation accent executed as the asset's own entrance (arrivals relation approach)
        # travels under the reference entry profile, not the in-place accent ceiling.
        return REFERENCE_SLIDE
    return motion_comfort(phase)


def accent_readability_floor(
    phase: str, *, segment_duration: float, active_duration: float | None,
    item_width: float, item_height: float,
) -> float:
    """Shared normalized floor for an INTERACT/REACT/PAYOFF segment (0 for other phases)."""
    phase = str(phase).upper()
    if phase not in SEMANTIC_ACCENT_PHASES:
        return 0.0
    duration = semantic_readability_duration(
        phase, segment_duration=max(1e-6, float(segment_duration)), active_duration=active_duration)
    return semantic_readability_floor(phase, item_width=item_width, item_height=item_height, duration=duration)


def semantic_accent_floor_violation(
    *, phase: str, program: Mapping, segment_duration: float, item_width: float, item_height: float,
) -> SegmentContractViolation | None:
    """``MOTION_BELOW_PERCEPTUAL_FLOOR`` for a semantic accent, exactly as rendered QA judges it."""
    if str(phase).upper() not in SEMANTIC_ACCENT_PHASES:
        return None
    try:
        active = float(program.get("semantic_active_duration", segment_duration))
    except (TypeError, ValueError):
        active = float(segment_duration)
    activity = keyframe_activity_normalized(program.get("keyframes"), item_width=item_width,
                                            item_height=item_height)
    floor = accent_readability_floor(phase, segment_duration=segment_duration, active_duration=active,
                                     item_width=item_width, item_height=item_height)
    if activity + 1e-9 < floor:
        return SegmentContractViolation(
            "MOTION_BELOW_PERCEPTUAL_FLOOR",
            f"expected normalized motion {activity:.5f} is below shared readability floor {floor:.5f}",
            activity, floor)
    return None


def comfort_speed_violation(
    *, phase: str, program: Mapping, params: Mapping | None, segment_duration: float,
    item_width: float, item_height: float,
) -> SegmentContractViolation | None:
    """``MOTION_TOO_FAST`` exactly as rendered QA judges it (QA tolerance included)."""
    duration = max(1e-6, float(segment_duration))
    speed = keyframe_peak_speed_normalized(program.get("keyframes"), duration=duration,
                                           item_width=item_width, item_height=item_height)
    profile = comfort_profile_for(phase, program_name=str(program.get("name") or ""), params=params)
    limit = profile.max_normalized_speed * QA_SPEED_TOLERANCE
    if speed > limit + 1e-6:
        return SegmentContractViolation(
            "MOTION_TOO_FAST",
            f"expected normalized peak speed {speed:.4f}/s exceeds comfort limit {limit:.4f}/s",
            speed, limit)
    return None


def perceptual_floor_px_violation(
    *, phase: str, program: Mapping, segment_duration: float, item_width: float, item_height: float,
    frame_width: int | None = None, frame_height: int | None = None,
) -> SegmentContractViolation | None:
    """Pixel floor of ENTRY/ESTABLISH/ADD/EXIT segments on an unprojected target
    (frame size from the active target unless given).

    Encoded QA applies this same shared formula (``semantic_readability_floor_px``),
    scaled by the plan projection for projected targets.
    """
    phase = str(phase).upper()
    if phase in SEMANTIC_ACCENT_PHASES:
        return None
    floor_px = semantic_readability_floor_px(
        phase, item_width=item_width, item_height=item_height,
        duration=semantic_readability_duration(phase, segment_duration=max(1e-6, float(segment_duration))),
        frame_width=frame_width, frame_height=frame_height)
    expected_px = 0.0
    for frame in program.get("keyframes") or []:
        try:
            expected_px = max(expected_px, projected_motion_activity_px(
                dx=float(frame.get("dx", 0.0)), dy=float(frame.get("dy", 0.0)),
                scale=float(frame.get("scale", 1.0)), item_width=item_width, item_height=item_height,
                frame_width=frame_width, frame_height=frame_height))
        except (TypeError, ValueError, AttributeError):
            continue
    if expected_px + 1e-6 < floor_px:
        return SegmentContractViolation(
            "MOTION_BELOW_PERCEPTUAL_FLOOR",
            f"expected motion {expected_px:.2f}px is below readable floor {floor_px:.2f}px",
            expected_px, floor_px)
    return None


def segment_contract_violations(
    *, phase: str, program: Mapping, params: Mapping | None, segment_duration: float,
    item_width: float, item_height: float, base_entry: bool = False,
    frame_width: int | None = None, frame_height: int | None = None,
) -> list[SegmentContractViolation]:
    """Every shared floor/comfort violation encoded QA would report for one candidate
    program on the reference (unprojected) target. ``base_entry`` is a cue's base
    program rendered without semantic segments: QA checks its speed, not a floor."""
    rows: list[SegmentContractViolation | None] = []
    if not base_entry:
        rows.append(semantic_accent_floor_violation(
            phase=phase, program=program, segment_duration=segment_duration,
            item_width=item_width, item_height=item_height))
        rows.append(perceptual_floor_px_violation(
            phase=phase, program=program, segment_duration=segment_duration,
            item_width=item_width, item_height=item_height,
            frame_width=frame_width, frame_height=frame_height))
    rows.append(comfort_speed_violation(
        phase=phase, program=program, params=params, segment_duration=segment_duration,
        item_width=item_width, item_height=item_height))
    return [row for row in rows if row is not None]
