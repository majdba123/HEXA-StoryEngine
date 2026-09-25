from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from app.models import MotionCue, MotionSegment, StoryBeat
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

    _NO_AUTOMATIC_REACTION_ACTIONS = {"COMPARE", "LOOP"}

    def inspect(
        self,
        *,
        story: list[StoryBeat],
        motion: list[MotionCue],
    ) -> MotionInteractionReport:
        violations: list[MotionInteractionViolation] = []
        checked_segments = 0
        by_asset = {(cue.beat_id, cue.asset_id): cue for cue in motion}
        activation_by_asset = {
            (beat.id, activation.asset_id): activation
            for beat in story
            for activation in beat.asset_activations
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

        checked_relations = 0
        for key, source in relations.items():
            checked_relations += 1
            beat_id, event_id, source_id, target_id, result_id, relationship = key
            action = str(source.semantic_action or "").upper()

            if target_id and action not in self._NO_AUTOMATIC_REACTION_ACTIONS:
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

            if result_id:
                payoff_event_ids = {event_id}
                result_activation = activation_by_asset.get((beat_id, result_id))
                if (
                    result_activation is not None
                    and result_activation.semantic_event_id
                    and (
                        result_activation.semantic_event_id == event_id
                        or (
                            event_id is not None
                            and event_id in result_activation.semantic_event_dependency_ids
                        )
                    )
                ):
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
        if not exact:
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
                "violations": [asdict(row) for row in report.violations[:12]],
                "violation_count": len(report.violations),
            },
        )
