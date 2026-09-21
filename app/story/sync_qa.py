from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from app.models import MotionCue, StoryBeat
from app.shared.errors import StageFailedError


@dataclass(frozen=True, slots=True)
class StorySyncReport:
    anchored_assets: int
    semantic_assets: int
    explicit_assets: int
    grouped_assets: int
    fallback_assets: int
    unbound_assets: int
    max_settle_delta_seconds: float
    violations: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return not self.violations


class StorySyncQA:
    """Verify that Story semantic anchors survive the Motion planning boundary."""

    _SYNC_TOLERANCE_SECONDS = 0.050
    _ANCHORED_POLICIES = frozenset({"SEMANTIC", "EXPLICIT", "GROUP"})

    def inspect(
        self,
        *,
        story: list[StoryBeat],
        motion: list[MotionCue],
    ) -> StorySyncReport:
        cues = {(cue.beat_id, cue.asset_id): cue for cue in motion}
        anchored = 0
        semantic = 0
        explicit = 0
        grouped = 0
        fallback = 0
        unbound = 0
        max_delta = 0.0
        violations: list[str] = []

        for beat in story:
            previous_anchor: float | None = None
            for activation in beat.asset_activations:
                if activation.policy == "FALLBACK":
                    fallback += 1
                    continue
                if activation.policy not in self._ANCHORED_POLICIES:
                    unbound += 1
                    continue
                if activation.spoken_start is None:
                    violations.append(
                        f"{beat.id}:{activation.asset_id}:anchored_without_spoken_time"
                    )
                    continue

                anchored += 1
                if activation.policy == "SEMANTIC":
                    semantic += 1
                elif activation.policy == "EXPLICIT":
                    explicit += 1
                elif activation.policy == "GROUP":
                    grouped += 1

                if (
                    previous_anchor is not None
                    and activation.policy != "GROUP"
                    and activation.spoken_start + 1e-9 < previous_anchor
                ):
                    violations.append(
                        f"{beat.id}:{activation.asset_id}:non_monotonic_story_anchor"
                    )
                if activation.policy != "GROUP":
                    previous_anchor = activation.spoken_start

                cue = cues.get((beat.id, activation.asset_id))
                if cue is None:
                    violations.append(
                        f"{beat.id}:{activation.asset_id}:missing_motion_cue"
                    )
                    continue

                raw_settle = cue.params.get("semantic_settle_time")
                try:
                    settle = float(raw_settle)
                except (TypeError, ValueError):
                    violations.append(
                        f"{beat.id}:{activation.asset_id}:missing_semantic_settle"
                    )
                    continue

                delta = abs(settle - activation.spoken_start)
                max_delta = max(max_delta, delta)
                if delta > self._SYNC_TOLERANCE_SECONDS:
                    violations.append(
                        f"{beat.id}:{activation.asset_id}:settle_delta={delta:.3f}"
                    )

        return StorySyncReport(
            anchored_assets=anchored,
            semantic_assets=semantic,
            explicit_assets=explicit,
            grouped_assets=grouped,
            fallback_assets=fallback,
            unbound_assets=unbound,
            max_settle_delta_seconds=round(max_delta, 6),
            violations=tuple(violations),
        )

    @staticmethod
    def require(report: StorySyncReport) -> None:
        if report.violations:
            raise StageFailedError(
                "semantic story synchronization contract failed",
                details={
                    "code": "STORY_SYNC_INVALID",
                    "violations": list(report.violations),
                    "max_settle_delta_seconds": report.max_settle_delta_seconds,
                },
            )

    @staticmethod
    def write(report: StorySyncReport, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(asdict(report), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
