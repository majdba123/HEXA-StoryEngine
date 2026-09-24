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
            sequence_motion: dict[
                str,
                list[tuple[int, float, str, bool, int | None, int | None]],
            ] = {}
            internal_motion: dict[
                tuple[str | None, int | None, str | None],
                list[tuple[int, int, float, float | None, float, bool, str]],
            ] = {}
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

                motion_order = cue.params.get("motion_order")
                if not isinstance(motion_order, dict):
                    motion_order = {}
                try:
                    internal_index = int(motion_order.get("internal_index", 0))
                    internal_count = int(motion_order.get("internal_count", 1))
                except (TypeError, ValueError):
                    internal_index, internal_count = 0, 1
                internal_stagger = bool(motion_order.get("stagger_applied"))
                ordered_visual_unit = internal_count > 1

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
                        # A claimed settle_progress cannot conceal an earlier arrival.
                        # Static/alpha-only programs have no spatial arrival to infer.
                        moving = [i for i, row in enumerate(program.keyframes)
                                  if abs(row.dx) > 1e-9 or abs(row.dy) > 1e-9
                                  or abs(row.scale - 1) > 1e-9]
                        if moving:
                            arrival = program.keyframes[moving[-1] + 1].progress
                            actual = cue.start + max(0.05, cue.end - cue.start) * arrival
                    except (KeyError, TypeError, ValueError, OverflowError):
                        violations.append(f"{beat.id}:{activation.asset_id}:invalid_visual_settle")
                        actual = None
                    if ordered_visual_unit:
                        if cue.start < window.reveal_start - self._SYNC_TOLERANCE_SECONDS - 1e-9:
                            violations.append(
                                f"{beat.id}:{activation.asset_id}:visual_unit_reveal_before_story_window"
                            )
                        if settle > target + self._SYNC_TOLERANCE_SECONDS + 1e-9:
                            violations.append(
                                f"{beat.id}:{activation.asset_id}:visual_unit_settle_after_story_window"
                            )
                        if (
                            actual is not None
                            and abs(actual - settle) > self._SYNC_TOLERANCE_SECONDS + 1e-9
                        ):
                            violations.append(
                                f"{beat.id}:{activation.asset_id}:visual_unit_actual_settle_mismatch"
                            )
                    elif (
                        abs(cue.start - window.reveal_start)
                        > self._SYNC_TOLERANCE_SECONDS + 1e-9
                    ):
                        violations.append(f"{beat.id}:{activation.asset_id}:reveal_start_mismatch")

                if ordered_visual_unit and window is not None:
                    delta = max(
                        0.0,
                        settle - target,
                        (actual - target) if actual is not None else 0.0,
                        window.reveal_start - cue.start,
                    )
                else:
                    delta = max(
                        abs(settle - target),
                        abs(actual - target) if actual is not None else 0.0,
                    )
                max_delta = max(max_delta, delta)
                if (
                    activation.source == "final_package_semantic_binding"
                    and activation.semantic_group_id
                    and activation.sequence_order is not None
                ):
                    sequence_motion.setdefault(
                        activation.semantic_group_id,
                        [],
                    ).append((
                        activation.sequence_order,
                        cue.start,
                        activation.asset_id,
                        "semantic_group_sequential_window" in activation.evidence,
                        activation.trigger_char_start,
                        activation.trigger_char_end,
                    ))
                if ordered_visual_unit:
                    key = (
                        activation.semantic_group_id,
                        activation.sequence_order,
                        activation.semantic_unit_id,
                    )
                    internal_motion.setdefault(key, []).append((
                        internal_index,
                        internal_count,
                        cue.start,
                        actual,
                        target,
                        internal_stagger,
                        activation.asset_id,
                    ))

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

            for group_id, rows in sequence_motion.items():
                by_order: dict[
                    int,
                    list[tuple[float, str, bool, int | None, int | None]],
                ] = {}
                for order, start_time, asset_id, scheduled, char_start, char_end in rows:
                    by_order.setdefault(order, []).append(
                        (
                            start_time,
                            asset_id,
                            scheduled,
                            char_start,
                            char_end,
                        )
                    )
                ordered_starts = [
                    (order, min(row[0] for row in by_order[order]))
                    for order in sorted(by_order)
                ]
                for (left_order, left_start), (right_order, right_start) in zip(
                    ordered_starts, ordered_starts[1:]
                ):
                    pair_rows = by_order[left_order] + by_order[right_order]
                    explicitly_scheduled = any(row[2] for row in pair_rows)
                    # sequence_order is enforceable only when Story deliberately
                    # allocated a shared precise phrase into sequential sub-windows.
                    # Distinct precise script spans are allowed to follow narration
                    # order even when that differs from a visual authoring hint.
                    if not explicitly_scheduled:
                        continue
                    if right_start + 1e-9 < left_start:
                        violations.append(
                            f"{beat.id}:{group_id}:sequence_order_motion_reversed:"
                            f"{left_order}>{right_order}"
                        )
                    if right_start <= left_start + 1e-9:
                        violations.append(
                            f"{beat.id}:{group_id}:sequence_order_motion_collapsed:"
                            f"{left_order}={right_order}"
                        )

            for key, rows in internal_motion.items():
                group_id, sequence_order, semantic_unit_id = key
                expected_count = max(row[1] for row in rows)
                ranks = sorted(row[0] for row in rows)
                if len(rows) != expected_count or ranks != list(range(expected_count)):
                    violations.append(
                        f"{beat.id}:{semantic_unit_id}:visual_unit_rank_incomplete"
                    )
                    continue
                ordered_rows = sorted(rows, key=lambda row: row[0])
                starts = [row[2] for row in ordered_rows]
                if any(right + 1e-9 < left for left, right in zip(starts, starts[1:])):
                    violations.append(
                        f"{beat.id}:{semantic_unit_id}:visual_unit_order_reversed"
                    )
                if all(row[5] for row in ordered_rows) and any(
                    right <= left + 1e-9 for left, right in zip(starts, starts[1:])
                ):
                    violations.append(
                        f"{beat.id}:{semantic_unit_id}:visual_unit_stagger_collapsed"
                    )
                final_actual = ordered_rows[-1][3]
                final_target = ordered_rows[-1][4]
                if (
                    all(row[5] for row in ordered_rows)
                    and final_actual is not None
                    and abs(final_actual - final_target)
                    > self._SYNC_TOLERANCE_SECONDS + 1e-9
                ):
                    violations.append(
                        f"{beat.id}:{group_id}:{sequence_order}:{semantic_unit_id}:"
                        "visual_unit_final_member_missed_story_settle"
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
