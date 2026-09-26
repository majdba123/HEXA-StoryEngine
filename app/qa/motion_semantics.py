from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from app.choreography import ChoreographyPlan
from app.choreography.relation_contract import relation_requires_reaction
from app.models import CompositionBeat, LayoutItem, MotionCue, MotionSegment, StoryBeat
from app.motion.collision import authored_overlap_ratio, max_relation_overlap
from app.qa.failure_identity import violation_failure_details
from app.shared.errors import StageFailedError


@dataclass(frozen=True, slots=True)
class MotionInteractionViolation:
    code: str
    beat_id: str
    asset_id: str | None
    event_id: str | None
    detail: str


@dataclass(frozen=True, slots=True)
class MotionInteractionReport:
    checked_segments: int
    checked_relations: int
    violations: tuple[MotionInteractionViolation, ...]

    @property
    def ok(self) -> bool:
        return not self.violations


class MotionInteractionQA:
    """Validate the semantic behavior Motion must express, not just metadata presence."""

    def inspect(
        self,
        *,
        story: list[StoryBeat],
        motion: list[MotionCue],
        composition: list[CompositionBeat] | None = None,
        choreography: ChoreographyPlan | None = None,
    ) -> MotionInteractionReport:
        violations: list[MotionInteractionViolation] = []
        checked_segments = 0
        by_asset = {(cue.beat_id, cue.asset_id): cue for cue in motion}
        activation_by_asset = {
            (beat.id, activation.asset_id): activation
            for beat in story
            for activation in beat.asset_activations
        }
        layout_by_asset = {
            (row.beat_id, item.asset_id): item
            for row in (composition or [])
            for item in row.items
        }

        for cue in motion:
            for segment in cue.segments:
                checked_segments += 1
                self._validate_segment(cue, segment, violations)

        relations: dict[
            tuple[str, str | None, str | None, str | None, str | None, str | None],
            MotionSegment,
        ] = {}
        for cue in motion:
            for segment in cue.segments:
                if segment.phase != "INTERACT" or segment.involvement != "SOURCE":
                    continue
                key = (
                    cue.beat_id,
                    segment.semantic_event_id,
                    segment.source_asset_id,
                    segment.target_asset_id,
                    segment.result_asset_id,
                    segment.relationship,
                )
                relations.setdefault(key, segment)

        if choreography is not None:
            represented = {
                (beat_id, source_id, target_id, result_id, relationship)
                for (
                    beat_id,
                    _event_id,
                    source_id,
                    target_id,
                    result_id,
                    relationship,
                ) in relations
            }
            expected: set[
                tuple[str, str | None, str | None, str | None, str | None]
            ] = set()
            for directive in choreography.directives:
                interactions = directive.interactions or (
                    (directive.interaction,) if directive.interaction is not None else ()
                )
                for interaction in interactions:
                    if not interaction.executable:
                        continue
                    if interaction.authority not in {
                        "FINAL_PACKAGE_ASSET_RELATION",
                        "FINAL_PACKAGE_INTERACTION_TARGET",
                    }:
                        continue
                    expected.add((
                        directive.beat_id,
                        interaction.subject_asset_id,
                        interaction.object_asset_id,
                        interaction.result_asset_id,
                        interaction.relationship,
                    ))
            for relation_key in sorted(expected - represented, key=str):
                beat_id, source_id, target_id, result_id, relationship = relation_key
                violations.append(MotionInteractionViolation(
                    code="MISSING_RELATION_TIMELINE",
                    beat_id=beat_id,
                    asset_id=source_id,
                    event_id=None,
                    detail=(
                        f"{relationship or 'relation'}: executable authored relation "
                        f"{source_id}->{target_id}"
                        + (f"->{result_id}" if result_id else "")
                        + " has no INTERACT source timeline"
                    ),
                ))

        checked_relations = 0
        for key, source in relations.items():
            checked_relations += 1
            beat_id, event_id, source_id, target_id, result_id, relationship = key
            action = str(source.semantic_action or "").upper()

            if relation_requires_reaction(
                semantic_action=action,
                executable=True,
                target_asset_id=target_id,
            ):
                target = self._find_segment(
                    by_asset.get((beat_id, target_id)),
                    event_id=event_id,
                    phases={"REACT"},
                    source_id=source_id,
                    target_id=target_id,
                )
                if target is None:
                    violations.append(MotionInteractionViolation(
                        code="MISSING_TARGET_REACTION",
                        beat_id=beat_id,
                        asset_id=target_id,
                        event_id=event_id,
                        detail=f"{relationship or action}: target has no REACT segment",
                    ))
                elif min(source.end, target.end) - max(source.start, target.start) <= 1e-6:
                    violations.append(MotionInteractionViolation(
                        code="NO_RELATION_OVERLAP",
                        beat_id=beat_id,
                        asset_id=target_id,
                        event_id=event_id,
                        detail=(
                            f"subject {source.start:.3f}-{source.end:.3f} and target "
                            f"{target.start:.3f}-{target.end:.3f} do not overlap"
                        ),
                    ))
                else:
                    self._validate_relation_collision(
                        beat_id=beat_id,
                        event_id=event_id,
                        source_id=source_id,
                        target_id=target_id,
                        source=source,
                        target=target,
                        source_cue=by_asset.get((beat_id, source_id)) if source_id else None,
                        target_cue=by_asset.get((beat_id, target_id)),
                        source_item=layout_by_asset.get((beat_id, source_id)) if source_id else None,
                        target_item=layout_by_asset.get((beat_id, target_id)),
                        violations=violations,
                    )

            if result_id:
                payoff_event_ids = {event_id}
                result_activation = activation_by_asset.get((beat_id, result_id))
                if result_activation is not None and result_activation.semantic_event_id:
                    # The explicit relation already names this exact asset as its result.
                    # If Story owns that asset in another semantic event, its PAYOFF may
                    # correctly execute there even when the package omitted a redundant
                    # dependency edge. Accept the result asset's own Story event rather
                    # than forcing Motion to steal event ownership.
                    payoff_event_ids.add(result_activation.semantic_event_id)

                payoff = self._find_payoff_segment(
                    by_asset.get((beat_id, result_id)),
                    event_ids=payoff_event_ids,
                )
                if payoff is None:
                    violations.append(MotionInteractionViolation(
                        code="MISSING_RESULT_PAYOFF",
                        beat_id=beat_id,
                        asset_id=result_id,
                        event_id=event_id,
                        detail=f"{relationship or action}: authored result has no PAYOFF segment",
                    ))
                elif payoff.start < source.start - 1e-6:
                    violations.append(MotionInteractionViolation(
                        code="PAYOFF_PRECEDES_CAUSE",
                        beat_id=beat_id,
                        asset_id=result_id,
                        event_id=event_id,
                        detail=(
                            f"payoff starts at {payoff.start:.3f} before interaction "
                            f"{source.start:.3f}"
                        ),
                    ))

        return MotionInteractionReport(
            checked_segments=checked_segments,
            checked_relations=checked_relations,
            violations=tuple(violations),
        )



    @classmethod
    def _validate_relation_collision(
        cls,
        *,
        beat_id: str,
        event_id: str | None,
        source_id: str | None,
        target_id: str,
        source: MotionSegment,
        target: MotionSegment,
        source_cue: MotionCue | None,
        target_cue: MotionCue | None,
        source_item: LayoutItem | None,
        target_item: LayoutItem | None,
        violations: list[MotionInteractionViolation],
    ) -> None:
        if source_item is None or target_item is None:
            return
        if cls._geometry_locked(source_cue) or cls._geometry_locked(target_cue):
            return
        overlap_start = max(float(source.start), float(target.start))
        overlap_end = min(float(source.end), float(target.end))
        if overlap_end <= overlap_start + 1e-6:
            return
        authored = authored_overlap_ratio(source_item, target_item)
        animated = max_relation_overlap(
            source=source,
            target=target,
            source_item=source_item,
            target_item=target_item,
        )
        if authored <= 0.02 and animated > 0.12 and animated > authored + 0.08:
            violations.append(MotionInteractionViolation(
                code="MOTION_CREATES_COLLISION",
                beat_id=beat_id,
                asset_id=target_id,
                event_id=event_id,
                detail=(
                    f"{source_id or 'source'}->{target_id} authored overlap "
                    f"{authored:.3f}, animated overlap {animated:.3f}"
                ),
            ))

    @staticmethod
    def _geometry_locked(cue: MotionCue | None) -> bool:
        if cue is None or not isinstance(cue.params, dict):
            return False
        constraints = cue.params.get("render_constraints")
        return (
            isinstance(constraints, dict)
            and constraints.get("geometry_lock") == "authored_footprint"
        )

    @classmethod
    def _segment_transform_at(
        cls,
        segment: MotionSegment,
        absolute_time: float,
    ) -> tuple[float, float, float]:
        keyframes = segment.program.get("keyframes")
        if not isinstance(keyframes, list) or not keyframes:
            return 0.0, 0.0, 1.0
        duration = max(1e-6, float(segment.end) - float(segment.start))
        progress = max(0.0, min(1.0, (float(absolute_time) - float(segment.start)) / duration))
        rows: list[tuple[float, float, float, float, str]] = []
        for frame in keyframes:
            try:
                rows.append((
                    float(frame.get("progress", 0.0)),
                    float(frame.get("dx", 0.0)),
                    float(frame.get("dy", 0.0)),
                    float(frame.get("scale", 1.0)),
                    str(frame.get("easing") or "linear"),
                ))
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
                span = max(1e-6, right[0] - left[0])
                p = (progress - left[0]) / span
                e = cls._ease(left[4], p)
                return (
                    left[1] + (right[1] - left[1]) * e,
                    left[2] + (right[2] - left[2]) * e,
                    left[3] + (right[3] - left[3]) * e,
                )
        return rows[-1][1], rows[-1][2], rows[-1][3]

    @staticmethod
    def _ease(name: str, value: float) -> float:
        p = max(0.0, min(1.0, value))
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
            c3 = c1 + 1
            return 1 + c3 * (p - 1) ** 3 + c1 * (p - 1) ** 2
        return 1 - (1 - p) ** 3

    @staticmethod
    def _box(
        item: LayoutItem,
        transform: tuple[float, float, float],
    ) -> tuple[float, float, float, float]:
        dx, dy, scale = transform
        width = max(0.0, float(item.width) * max(0.0, scale))
        height = max(0.0, float(item.height) * max(0.0, scale))
        cx = float(item.x) + dx
        cy = float(item.y) + dy
        return (
            cx - width / 2,
            cy - height / 2,
            cx + width / 2,
            cy + height / 2,
        )

    @staticmethod
    def _overlap_ratio(
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

    @staticmethod
    def _find_payoff_segment(
        cue: MotionCue | None,
        *,
        event_ids: set[str | None],
    ) -> MotionSegment | None:
        """Find a result payoff in the relation event or its authored dependent event.

        Final Package V1.2 may model cause and result as separate semantic events:
        E1 interaction -> E2 result, where E2 depends on E1. In that case the PAYOFF
        correctly belongs to E2 and does not need to duplicate E1 source/target fields.
        """
        if cue is None:
            return None
        rows = [
            row
            for row in cue.segments
            if row.phase == "PAYOFF" and row.semantic_event_id in event_ids
        ]
        return min(rows, key=lambda row: (row.start, row.end)) if rows else None

    @staticmethod
    def _find_segment(
        cue: MotionCue | None,
        *,
        event_id: str | None,
        phases: set[str],
        source_id: str | None,
        target_id: str | None,
    ) -> MotionSegment | None:
        if cue is None:
            return None
        rows = [
            row for row in cue.segments
            if row.phase in phases
            and row.semantic_event_id == event_id
            and row.source_asset_id == source_id
            and row.target_asset_id == target_id
        ]
        return min(rows, key=lambda row: (row.start, row.end)) if rows else None

    @staticmethod
    def _validate_segment(
        cue: MotionCue,
        segment: MotionSegment,
        violations: list[MotionInteractionViolation],
    ) -> None:
        if segment.handoff_deadline is not None and segment.end > segment.handoff_deadline + 1e-6:
            violations.append(MotionInteractionViolation(
                code="SEGMENT_PAST_HANDOFF",
                beat_id=cue.beat_id,
                asset_id=cue.asset_id,
                event_id=segment.semantic_event_id,
                detail=(
                    f"{segment.phase} ends {segment.end:.3f} after handoff "
                    f"{segment.handoff_deadline:.3f}"
                ),
            ))
        keyframes = segment.program.get("keyframes")
        if not isinstance(keyframes, list) or not keyframes:
            violations.append(MotionInteractionViolation(
                code="SEGMENT_PROGRAM_MISSING",
                beat_id=cue.beat_id,
                asset_id=cue.asset_id,
                event_id=segment.semantic_event_id,
                detail=f"{segment.phase} has no executable keyframes",
            ))
            return
        final = keyframes[-1]
        try:
            exact = (
                abs(float(final.get("dx", 0.0))) <= 1e-9
                and abs(float(final.get("dy", 0.0))) <= 1e-9
                and abs(float(final.get("scale", 1.0)) - 1.0) <= 1e-9
            )
        except (TypeError, ValueError):
            exact = False
        if segment.phase == "EXIT":
            try:
                exit_activity = max(
                    abs(float(final.get("dx", 0.0))),
                    abs(float(final.get("dy", 0.0))),
                    abs(float(final.get("scale", 1.0)) - 1.0),
                )
            except (TypeError, ValueError):
                exit_activity = 0.0
            if exit_activity < 0.035:
                violations.append(MotionInteractionViolation(
                    code="EXIT_NOT_READABLE",
                    beat_id=cue.beat_id,
                    asset_id=cue.asset_id,
                    event_id=segment.semantic_event_id,
                    detail="EXIT does not travel far enough to read before disappearance",
                ))
        elif not exact:
            violations.append(MotionInteractionViolation(
                code="SEGMENT_GEOMETRY_DRIFT",
                beat_id=cue.beat_id,
                asset_id=cue.asset_id,
                event_id=segment.semantic_event_id,
                detail=f"{segment.phase} does not settle to exact Composition geometry",
            ))

    @staticmethod
    def write(report: MotionInteractionReport, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({
                "ok": report.ok,
                "checked_segments": report.checked_segments,
                "checked_relations": report.checked_relations,
                "violations": [asdict(row) for row in report.violations],
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def require(report: MotionInteractionReport) -> None:
        if report.ok:
            return
        raise StageFailedError(
            "semantic motion timeline QA failed",
            details={
                **violation_failure_details(
                    report.violations,
                    aggregate_code="MOTION_CONTRACT_VIOLATIONS",
                ),
                "violations": [asdict(row) for row in report.violations[:12]],
            },
        )
