from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from app.contracts import ContinuityContract
from app.models import CompositionBeat, MotionCue, StoryBeat
from app.render.transition import SceneTransitionMode, VisualTransitionPolicy
from app.shared.errors import StageFailedError


@dataclass(frozen=True, slots=True)
class SceneContinuityViolation:
    code: str
    from_beat_id: str
    to_beat_id: str
    detail: str


@dataclass(frozen=True, slots=True)
class SceneContinuityReport:
    checked_boundaries: int
    bridged_boundaries: int
    blur_boundaries: int
    violations: tuple[SceneContinuityViolation, ...]

    @property
    def ok(self) -> bool:
        return not self.violations


class SceneContinuityQA:
    """Validate scene-to-scene handoff contracts before FFmpeg rendering."""

    def __init__(self) -> None:
        self.policy = VisualTransitionPolicy()
        self.lifecycle = ContinuityContract()

    def inspect(
        self,
        *,
        story: list[StoryBeat],
        composition: list[CompositionBeat],
        motion: list[MotionCue],
    ) -> SceneContinuityReport:
        layouts = {row.beat_id: row for row in composition}
        motion_by_beat: dict[str, list[MotionCue]] = {}
        motion_by_key: dict[tuple[str, str], MotionCue] = {}
        for cue in motion:
            motion_by_beat.setdefault(cue.beat_id, []).append(cue)
            motion_by_key[(cue.beat_id, cue.asset_id)] = cue

        ordered = sorted(story, key=lambda row: (row.start, row.end, row.id))
        checked = 0
        bridged = 0
        blurred = 0
        violations: list[SceneContinuityViolation] = []

        for previous, current in zip(ordered, ordered[1:]):
            previous_layout = layouts.get(previous.id)
            current_layout = layouts.get(current.id)
            if previous_layout is None or current_layout is None:
                continue

            lifecycle = self.lifecycle.classify_boundary(
                previous_layout=previous_layout,
                current_layout=current_layout,
                previous_motion_by_asset={
                    item.asset_id: motion_by_key.get((previous.id, item.asset_id))
                    for item in previous_layout.items
                    if motion_by_key.get((previous.id, item.asset_id)) is not None
                },
            )
            for asset_id in sorted(lifecycle.invalid_terminal_persistence):
                violations.append(SceneContinuityViolation(
                    code="TERMINAL_EXIT_ON_PERSISTENT_ASSET",
                    from_beat_id=previous.id,
                    to_beat_id=current.id,
                    detail=(
                        f"{asset_id} has terminal EXIT/LEAVE in {previous.id} but the exact "
                        f"same asset is authored in adjacent beat {current.id}; this would "
                        "produce disappear/reappear lifecycle discontinuity"
                    ),
                ))

            if previous.scene_id == current.scene_id:
                continue

            checked += 1
            decision = self.policy.decide(
                previous,
                previous_layout,
                current_layout,
                current_beat=current,
            )
            previous_ids = {item.asset_id for item in previous_layout.items}
            current_ids = {item.asset_id for item in current_layout.items}
            distinct_outgoing = previous_ids - current_ids

            if distinct_outgoing and decision.mode not in {
                SceneTransitionMode.OBJECT_HANDOFF,
                SceneTransitionMode.MOTION_HANDOFF,
                SceneTransitionMode.BLUR_BRIDGE,
            }:
                violations.append(SceneContinuityViolation(
                    code="MISSING_SCENE_BRIDGE",
                    from_beat_id=previous.id,
                    to_beat_id=current.id,
                    detail=(
                        f"cross-scene boundary with {len(distinct_outgoing)} outgoing "
                        f"assets resolved to {decision.mode.value}"
                    ),
                ))
                continue

            if decision.mode in {
                SceneTransitionMode.OBJECT_HANDOFF,
                SceneTransitionMode.MOTION_HANDOFF,
                SceneTransitionMode.BLUR_BRIDGE,
            }:
                bridged += 1
                if not decision.carry_outgoing_asset_ids:
                    violations.append(SceneContinuityViolation(
                        code="EMPTY_SCENE_BRIDGE",
                        from_beat_id=previous.id,
                        to_beat_id=current.id,
                        detail="bridge mode selected without any outgoing visual carrier",
                    ))
                if decision.bridge_duration < 0.20:
                    violations.append(SceneContinuityViolation(
                        code="SCENE_BRIDGE_TOO_SHORT",
                        from_beat_id=previous.id,
                        to_beat_id=current.id,
                        detail=f"bridge duration is {decision.bridge_duration:.3f}s",
                    ))

            if decision.mode == SceneTransitionMode.BLUR_BRIDGE:
                blurred += 1
                if decision.reason != "explicit_blur_intent":
                    violations.append(SceneContinuityViolation(
                        code="BLUR_NOT_EXPLICITLY_AUTHORED",
                        from_beat_id=previous.id,
                        to_beat_id=current.id,
                        detail=f"blur reason was {decision.reason!r}",
                    ))
                if decision.blur_sigma <= 0:
                    violations.append(SceneContinuityViolation(
                        code="BLUR_BRIDGE_WITHOUT_BLUR",
                        from_beat_id=previous.id,
                        to_beat_id=current.id,
                        detail="authored blur handoff has zero blur strength",
                    ))
            elif decision.blur_sigma > 0:
                violations.append(SceneContinuityViolation(
                    code="UNAUTHORED_BLUR",
                    from_beat_id=previous.id,
                    to_beat_id=current.id,
                    detail=(
                        f"{decision.mode.value} unexpectedly carries blur "
                        f"sigma={decision.blur_sigma:.3f}"
                    ),
                ))

            beat_duration = max(0.0, float(current.end) - float(current.start))
            if decision.bridge_duration > beat_duration + 1e-6:
                violations.append(SceneContinuityViolation(
                    code="SCENE_BRIDGE_OVERRUN",
                    from_beat_id=previous.id,
                    to_beat_id=current.id,
                    detail=(
                        f"bridge {decision.bridge_duration:.3f}s exceeds "
                        f"beat duration {beat_duration:.3f}s"
                    ),
                ))

            for cue in motion_by_beat.get(current.id, []):
                if cue.start < current.start - 0.04:
                    violations.append(SceneContinuityViolation(
                        code="INCOMING_BEFORE_STORY",
                        from_beat_id=previous.id,
                        to_beat_id=current.id,
                        detail=(
                            f"{cue.asset_id} begins at {cue.start:.3f}s before "
                            f"beat {current.start:.3f}s"
                        ),
                    ))

        return SceneContinuityReport(
            checked_boundaries=checked,
            bridged_boundaries=bridged,
            blur_boundaries=blurred,
            violations=tuple(violations),
        )

    @staticmethod
    def write(report: SceneContinuityReport, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({
                "ok": report.ok,
                "checked_boundaries": report.checked_boundaries,
                "bridged_boundaries": report.bridged_boundaries,
                "blur_boundaries": report.blur_boundaries,
                "violations": [asdict(row) for row in report.violations],
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def require(report: SceneContinuityReport) -> None:
        if report.ok:
            return
        raise StageFailedError(
            "scene continuity QA failed",
            details={
                "violation_count": len(report.violations),
                "violations": [asdict(row) for row in report.violations[:12]],
            },
        )
