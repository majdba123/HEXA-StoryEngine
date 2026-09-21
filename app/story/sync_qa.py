from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from math import isfinite

from app.models import MotionCue, StoryBeat
from app.shared.errors import StageFailedError


@dataclass(frozen=True, slots=True)
class StorySyncEntry:
    beat_id: str
    asset_id: str
    semantic_unit_id: str | None
    trigger_text: str | None
    policy: str
    source: str
    confidence: float
    spoken_start: float | None
    motion_settle: float | None
    settle_delta_seconds: float | None
    activation_policy: str | None = None
    reveal_start: float | None = None
    semantic_peak: float | None = None
    settle_target: float | None = None
    actual_visual_settle: float | None = None


@dataclass(frozen=True, slots=True)
class StorySyncReport:
    anchored_assets: int
    semantic_assets: int
    explicit_assets: int
    grouped_assets: int
    fallback_assets: int
    unbound_assets: int
    max_settle_delta_seconds: float
    entries: tuple[StorySyncEntry, ...]
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
        from app.motion.models import MotionKeyframe, MotionProgram
        from app.motion.timing import story_activation_window

        cues = {(cue.beat_id, cue.asset_id): cue for cue in motion}
        anchored = 0
        semantic = 0
        explicit = 0
        grouped = 0
        fallback = 0
        unbound = 0
        max_delta = 0.0
        entries: list[StorySyncEntry] = []
        violations: list[str] = []

        for beat in story:
            previous_anchor: float | None = None
            for activation in beat.asset_activations:
                has_v2, window = story_activation_window(activation, beat)
                activation_policy = (
                    window.activation_policy if window is not None
                    else "SAFE_ABSTENTION" if has_v2 else None
                )
                if (has_v2 and window is None) or (not has_v2 and activation.policy == "FALLBACK"):
                    fallback += 1
                    entries.append(StorySyncEntry(
                        beat_id=beat.id,
                        asset_id=activation.asset_id,
                        semantic_unit_id=activation.semantic_unit_id,
                        trigger_text=activation.trigger_text,
                        policy=activation.policy,
                        source=activation.source,
                        confidence=activation.confidence,
                        spoken_start=activation.spoken_start,
                        motion_settle=None,
                        settle_delta_seconds=None,
                        activation_policy=activation_policy,
                    ))
                    continue
                if not has_v2 and activation.policy not in self._ANCHORED_POLICIES:
                    unbound += 1
                    continue
                target = window.settle_at if window is not None else activation.spoken_start
                if target is None or not isfinite(target):
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
                    and activation.spoken_start is not None
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
                    if not isfinite(settle):
                        raise ValueError("nonfinite semantic settle")
                except (TypeError, ValueError):
                    violations.append(
                        f"{beat.id}:{activation.asset_id}:missing_semantic_settle"
                    )
                    continue

                actual = None
                if window is not None:
                    try:
                        payload = cue.params["program"]
                        program = MotionProgram(
                            name=payload["name"],
                            settle_progress=float(payload["settle_progress"]),
                            keyframes=tuple(MotionKeyframe(**row) for row in payload["keyframes"]),
                        )
                        if not (isfinite(cue.start) and isfinite(cue.end)
                                and beat.start <= cue.start < cue.end <= beat.end):
                            raise ValueError("invalid cue bounds")
                        # Same effective duration as the renderer, including short windows.
                        actual = cue.start + max(0.05, cue.end - cue.start) * program.settle_progress
                        if any(abs(row.dx) > 1e-9 or abs(row.dy) > 1e-9 or abs(row.scale - 1) > 1e-9
                               for row in program.keyframes if row.progress >= program.settle_progress):
                            raise ValueError("motion does not hold final composition state")
                    except (KeyError, TypeError, ValueError, OverflowError):
                        violations.append(f"{beat.id}:{activation.asset_id}:invalid_visual_settle")
                        actual = None
                    if abs(cue.start - window.reveal_start) > self._SYNC_TOLERANCE_SECONDS + 1e-9:
                        violations.append(f"{beat.id}:{activation.asset_id}:reveal_start_mismatch")

                delta = max(abs(settle - target), abs(actual - target) if actual is not None else 0.0)
                max_delta = max(max_delta, delta)
                entries.append(StorySyncEntry(
                    beat_id=beat.id,
                    asset_id=activation.asset_id,
                    semantic_unit_id=activation.semantic_unit_id,
                    trigger_text=activation.trigger_text,
                    policy=activation.policy,
                    source=activation.source,
                    confidence=activation.confidence,
                    spoken_start=(round(activation.spoken_start, 6)
                                  if activation.spoken_start is not None else None),
                    motion_settle=round(settle, 6),
                    settle_delta_seconds=round(delta, 6),
                    activation_policy=activation_policy,
                    reveal_start=window.reveal_start if window else None,
                    semantic_peak=window.semantic_peak if window else None,
                    settle_target=target,
                    actual_visual_settle=round(actual, 6) if actual is not None else None,
                ))
                if delta > self._SYNC_TOLERANCE_SECONDS + 1e-9:
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
            entries=tuple(entries),
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
