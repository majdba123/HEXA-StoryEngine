from __future__ import annotations

from app.models import CompositionBeat, LayoutItem, MotionCue, MotionSegment


_AUTHORED_SEPARATION_LIMIT = 0.02
_SAFE_ANIMATED_OVERLAP = 0.08
_BINARY_STEPS = 16


def geometry_locked(cue: MotionCue | None) -> bool:
    if cue is None or not isinstance(cue.params, dict):
        return False
    constraints = cue.params.get("render_constraints")
    return (
        isinstance(constraints, dict)
        and constraints.get("geometry_lock") == "authored_footprint"
    )


def authored_overlap_ratio(source: LayoutItem, target: LayoutItem) -> float:
    return overlap_ratio(box(source, (0.0, 0.0, 1.0)), box(target, (0.0, 0.0, 1.0)))


def max_relation_overlap(
    *,
    source: MotionSegment,
    target: MotionSegment,
    source_item: LayoutItem,
    target_item: LayoutItem,
    samples: int = 17,
) -> float:
    start = max(float(source.start), float(target.start))
    end = min(float(source.end), float(target.end))
    if end <= start + 1e-9:
        return 0.0

    times = {start, end, start + (end - start) * 0.5}
    count = max(3, int(samples))
    for index in range(count):
        times.add(start + (end - start) * index / max(1, count - 1))
    for segment in (source, target):
        duration = max(1e-9, float(segment.end) - float(segment.start))
        keyframes = segment.program.get("keyframes")
        if not isinstance(keyframes, list):
            continue
        for frame in keyframes:
            try:
                absolute = float(segment.start) + duration * float(frame.get("progress", 0.0))
            except (TypeError, ValueError):
                continue
            if start <= absolute <= end:
                times.add(absolute)

    return max(
        overlap_ratio(
            box(source_item, segment_transform_at(source, moment)),
            box(target_item, segment_transform_at(target, moment)),
        )
        for moment in sorted(times)
    )


def fit_relation_collisions(
    cues: list[MotionCue],
    layout: CompositionBeat,
) -> list[MotionCue]:
    """Reduce only relation amplitude that would create a new visual collision.

    Composition remains authoritative. Timing, direction, semantic roles and easing stay
    unchanged; only dx/dy/scale deltas are uniformly reduced, and only when previously
    separated authored boxes would overlap materially during INTERACT/REACT.
    """
    if len(cues) < 2 or not layout.items:
        return cues

    items = {item.asset_id: item for item in layout.items}
    cue_index = {cue.asset_id: index for index, cue in enumerate(cues)}
    segments = [list(cue.segments) for cue in cues]
    seen: set[tuple[str, str, str | None, str | None, float, float]] = set()

    for source_cue_index, cue in enumerate(cues):
        if geometry_locked(cue):
            continue
        for source_segment_index, source_segment in enumerate(list(segments[source_cue_index])):
            if source_segment.phase != "INTERACT":
                continue
            source_id = source_segment.source_asset_id or cue.asset_id
            target_id = source_segment.target_asset_id
            if not target_id or source_id not in items or target_id not in items:
                continue
            target_cue_index = cue_index.get(target_id)
            if target_cue_index is None or geometry_locked(cues[target_cue_index]):
                continue

            candidates: list[tuple[int, MotionSegment]] = []
            for target_segment_index, target_segment in enumerate(segments[target_cue_index]):
                if target_segment.phase != "REACT":
                    continue
                if (
                    target_segment.source_asset_id
                    and target_segment.source_asset_id != source_id
                ):
                    continue
                if (
                    target_segment.target_asset_id
                    and target_segment.target_asset_id != target_id
                ):
                    continue
                if (
                    source_segment.relationship
                    and target_segment.relationship
                    and source_segment.relationship != target_segment.relationship
                ):
                    continue
                if min(source_segment.end, target_segment.end) <= max(
                    source_segment.start, target_segment.start
                ) + 1e-9:
                    continue
                candidates.append((target_segment_index, target_segment))
            if not candidates:
                continue

            target_segment_index, target_segment = max(
                candidates,
                key=lambda row: min(source_segment.end, row[1].end)
                - max(source_segment.start, row[1].start),
            )
            key = (
                source_id,
                target_id,
                source_segment.semantic_event_id,
                source_segment.relationship,
                float(source_segment.start),
                float(target_segment.start),
            )
            if key in seen:
                continue
            seen.add(key)

            source_item = items[source_id]
            target_item = items[target_id]
            authored = authored_overlap_ratio(source_item, target_item)
            if authored > _AUTHORED_SEPARATION_LIMIT:
                continue

            current = max_relation_overlap(
                source=source_segment,
                target=target_segment,
                source_item=source_item,
                target_item=target_item,
            )
            if current <= _SAFE_ANIMATED_OVERLAP:
                continue

            low, high = 0.0, 1.0
            for _ in range(_BINARY_STEPS):
                gain = (low + high) * 0.5
                trial_source = scale_segment(source_segment, gain)
                trial_target = scale_segment(target_segment, gain)
                overlap = max_relation_overlap(
                    source=trial_source,
                    target=trial_target,
                    source_item=source_item,
                    target_item=target_item,
                )
                if overlap <= _SAFE_ANIMATED_OVERLAP:
                    low = gain
                else:
                    high = gain

            gain = max(0.0, min(1.0, low))
            fitted_source = scale_segment(
                source_segment,
                gain,
                collision_limited=True,
                authored_overlap=authored,
                original_overlap=current,
            )
            fitted_target = scale_segment(
                target_segment,
                gain,
                collision_limited=True,
                authored_overlap=authored,
                original_overlap=current,
            )
            segments[source_cue_index][source_segment_index] = fitted_source
            segments[target_cue_index][target_segment_index] = fitted_target

    return [
        cue.model_copy(update={"segments": rows})
        for cue, rows in zip(cues, segments)
    ]


def scale_segment(
    segment: MotionSegment,
    gain: float,
    *,
    collision_limited: bool = False,
    authored_overlap: float | None = None,
    original_overlap: float | None = None,
) -> MotionSegment:
    gain = max(0.0, min(1.0, float(gain)))
    program = dict(segment.program)
    keyframes = program.get("keyframes")
    if not isinstance(keyframes, list):
        return segment

    scaled: list[dict] = []
    for frame in keyframes:
        row = dict(frame)
        try:
            row["dx"] = float(row.get("dx", 0.0)) * gain
            row["dy"] = float(row.get("dy", 0.0)) * gain
            scale = float(row.get("scale", 1.0))
            row["scale"] = 1.0 + (scale - 1.0) * gain
        except (TypeError, ValueError):
            pass
        scaled.append(row)
    program["keyframes"] = scaled

    if collision_limited:
        program["collision_limited"] = True
        program["collision_gain"] = round(gain, 6)
        program["collision_policy"] = "preserve_authored_separation"
        if authored_overlap is not None:
            program["collision_authored_overlap"] = round(float(authored_overlap), 6)
        if original_overlap is not None:
            program["collision_original_overlap"] = round(float(original_overlap), 6)
        program["collision_overlap_limit"] = _SAFE_ANIMATED_OVERLAP

    return segment.model_copy(update={"program": program})


def segment_transform_at(
    segment: MotionSegment,
    absolute_time: float,
) -> tuple[float, float, float]:
    keyframes = segment.program.get("keyframes")
    if not isinstance(keyframes, list) or not keyframes:
        return 0.0, 0.0, 1.0
    duration = max(1e-9, float(segment.end) - float(segment.start))
    progress = max(
        0.0,
        min(1.0, (float(absolute_time) - float(segment.start)) / duration),
    )
    rows: list[tuple[float, float, float, float, str]] = []
    for frame in keyframes:
        try:
            rows.append(
                (
                    float(frame.get("progress", 0.0)),
                    float(frame.get("dx", 0.0)),
                    float(frame.get("dy", 0.0)),
                    float(frame.get("scale", 1.0)),
                    str(frame.get("easing") or "linear"),
                )
            )
        except (TypeError, ValueError):
            continue
    rows.sort(key=lambda row: row[0])
    if not rows:
        return 0.0, 0.0, 1.0
    if progress <= rows[0][0]:
        return rows[0][1], rows[0][2], rows[0][3]
    if progress >= rows[-1][0]:
        return rows[-1][1], rows[-1][2], rows[-1][3]

    for left, right in zip(rows, rows[1:]):
        if left[0] <= progress <= right[0]:
            span = max(1e-9, right[0] - left[0])
            local = (progress - left[0]) / span
            eased = ease(left[4], local)
            return (
                left[1] + (right[1] - left[1]) * eased,
                left[2] + (right[2] - left[2]) * eased,
                left[3] + (right[3] - left[3]) * eased,
            )
    return rows[-1][1], rows[-1][2], rows[-1][3]


def ease(name: str, value: float) -> float:
    p = max(0.0, min(1.0, float(value)))
    if name == "linear":
        return p
    if name == "ease_in_cubic":
        return p ** 3
    if name == "ease_in_out_cubic":
        return 4 * p ** 3 if p < 0.5 else 1 - ((-2 * p + 2) ** 3) / 2
    if name == "smoothstep":
        return 3 * p * p - 2 * p * p * p
    if name == "ease_out_expo":
        return 1.0 if p >= 1.0 else 1 - 2 ** (-10 * p)
    if name == "ease_out_back":
        c1 = 1.70158
        c3 = c1 + 1.0
        return 1.0 + c3 * (p - 1.0) ** 3 + c1 * (p - 1.0) ** 2
    return 1.0 - (1.0 - p) ** 3


def box(
    item: LayoutItem,
    transform: tuple[float, float, float],
) -> tuple[float, float, float, float]:
    dx, dy, scale = transform
    width = max(0.0, float(item.width) * max(0.0, scale))
    height = max(0.0, float(item.height) * max(0.0, scale))
    cx = float(item.x) + dx
    cy = float(item.y) + dy
    return (
        cx - width / 2.0,
        cy - height / 2.0,
        cx + width / 2.0,
        cy + height / 2.0,
    )


def overlap_ratio(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
) -> float:
    left = max(first[0], second[0])
    top = max(first[1], second[1])
    right = min(first[2], second[2])
    bottom = min(first[3], second[3])
    if right <= left or bottom <= top:
        return 0.0
    intersection = (right - left) * (bottom - top)
    first_area = max(1e-9, (first[2] - first[0]) * (first[3] - first[1]))
    second_area = max(1e-9, (second[2] - second[0]) * (second[3] - second[1]))
    return intersection / min(first_area, second_area)
