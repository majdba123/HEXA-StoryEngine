from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from app.choreography import ChoreographyPlan
from app.models import MotionCue, StoryBeat
from app.motion.event_flow import MotionEventFlowResolver
from app.motion.lifetime import SemanticVisualLifetimeIndex
from app.qa.failure_identity import violation_failure_details
from app.shared.errors import StageFailedError


@dataclass(frozen=True, slots=True)
class SemanticLifetimeViolation:
    code: str
    beat_id: str
    asset_id: str
    exit_end: float
    keep_visible_through: float
    detail: str


@dataclass(frozen=True, slots=True)
class SemanticLifetimeReport:
    checked_assets: int
    protected_assets: int
    violations: tuple[SemanticLifetimeViolation, ...]

    @property
    def ok(self) -> bool:
        return not self.violations


class SemanticLifetimeQA:
    """Reject terminal releases that precede proven future semantic use."""

    def __init__(self) -> None:
        self.event_flow = MotionEventFlowResolver()

    def inspect(
        self,
        *,
        story: list[StoryBeat],
        motion: list[MotionCue],
        choreography: ChoreographyPlan | None,
    ) -> SemanticLifetimeReport:
        cues = {(cue.beat_id, cue.asset_id): cue for cue in motion}
        checked = 0
        protected = 0
        violations: list[SemanticLifetimeViolation] = []

        for beat in story:
            directive = choreography.for_beat(beat.id) if choreography else None
            if directive is None or not directive.event_flows:
                continue
            semantic_event_by_asset = {
                activation.asset_id: activation.semantic_event_id
                for activation in beat.asset_activations
            }
            asset_ids = sorted(
                {
                    *semantic_event_by_asset,
                    *(proxy.asset_id for proxy in beat.semantic_event_proxies),
                    *(cue.asset_id for cue in motion if cue.beat_id == beat.id),
                }
            )
            assignments = self.event_flow.resolve_all(
                directive,
                asset_ids,
                semantic_event_by_asset=semantic_event_by_asset,
            )
            lifetime = SemanticVisualLifetimeIndex.build(
                beat=beat,
                directive=directive,
                assignments=assignments,
            )

            for asset_id in asset_ids:
                decision = lifetime.for_asset(asset_id)
                if decision is None:
                    continue
                checked += 1
                protected += 1
                cue = cues.get((beat.id, asset_id))
                if cue is None:
                    continue
                exits = [
                    segment
                    for segment in cue.segments
                    if segment.phase == "EXIT"
                    and segment.program.get("terminal_behavior") == "LEAVE"
                ]
                for exit_segment in exits:
                    if float(exit_segment.end) + 1e-6 >= decision.keep_visible_through:
                        continue
                    violations.append(
                        SemanticLifetimeViolation(
                            code="PREMATURE_SEMANTIC_EXIT",
                            beat_id=beat.id,
                            asset_id=asset_id,
                            exit_end=float(exit_segment.end),
                            keep_visible_through=decision.keep_visible_through,
                            detail=(
                                f"terminal EXIT ends at {exit_segment.end:.3f}s before "
                                f"future semantic use through "
                                f"{decision.keep_visible_through:.3f}s; "
                                f"future_events={list(decision.future_event_ids)}; "
                                f"reasons={list(decision.reasons)}"
                            ),
                        )
                    )

        return SemanticLifetimeReport(
            checked_assets=checked,
            protected_assets=protected,
            violations=tuple(violations),
        )

    @staticmethod
    def write(report: SemanticLifetimeReport, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "ok": report.ok,
                    "checked_assets": report.checked_assets,
                    "protected_assets": report.protected_assets,
                    "violations": [asdict(row) for row in report.violations],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    @staticmethod
    def require(report: SemanticLifetimeReport) -> None:
        if report.ok:
            return
        raise StageFailedError(
            "semantic visual lifetime QA failed",
            details={
                **violation_failure_details(
                    report.violations,
                    aggregate_code="SEMANTIC_LIFETIME_VIOLATIONS",
                ),
                "violations": [asdict(row) for row in report.violations[:12]],
            },
        )
