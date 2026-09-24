from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from math import isfinite

from app.models import AssetActivation, MotionCue, StoryBeat
from app.shared.errors import StageFailedError
from app.story.windows import same_precise_trigger


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
    actual_reveal: float | None = None
    actual_peak: float | None = None
    next_semantic_target: float | None = None


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
            trusted_windows: list[tuple[AssetActivation, object]] = []
            for activation in beat.asset_activations:
                has_v2, candidate = story_activation_window(activation, beat)
                if has_v2 and candidate is not None and activation.policy != "GROUP":
                    trusted_windows.append((activation, candidate))
            previous_anchor: float | None = None
            sequence_motion: dict[
                str,
                list[tuple[int, float, AssetActivation, bool]],
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
                actual_peak = None
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
                        focus_frames = [
                            row for row in program.keyframes
                            if row.progress <= program.settle_progress + 1e-9
                        ]
                        attention_frames = [
                            row
                            for row in focus_frames
                            if (
                                abs(row.dx) > 1e-9
                                or abs(row.dy) > 1e-9
                                or abs(row.scale - 1.0) > 1e-9
                            )
                        ]
                        # Footprint-locked Pass2 family layers are intentionally
                        # alpha-only/static: they have a reveal time but no spatial
                        # gesture peak. Do not manufacture a late peak from the last
                        # neutral keyframe; reveal/settle contracts still apply.
                        if attention_frames:
                            peak_frame = max(
                                attention_frames,
                                key=lambda row: (
                                    max(0.0, row.scale - 1.0),
                                    abs(row.dx) + abs(row.dy),
                                    row.progress,
                                ),
                            )
                            actual_peak = cue.start + max(0.05, cue.end - cue.start) * peak_frame.progress
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
                        activation,
                        "semantic_group_sequential_window" in activation.evidence,
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
                    semantic_peak=(
                        float(cue.params["semantic_peak_time"])
                        if window is not None
                        and ordered_visual_unit
                        and "semantic_peak_time" in cue.params
                        else window.semantic_peak if window else None
                    ),
                    settle_target=target,
                    actual_visual_settle=round(actual, 6) if actual is not None else None,
                    actual_reveal=round(cue.start, 6),
                    actual_peak=round(actual_peak, 6) if actual_peak is not None else None,
                    next_semantic_target=min(
                        (
                            float(candidate_window.reveal_start)
                            for candidate_activation, candidate_window in trusted_windows
                            if candidate_activation.asset_id != activation.asset_id
                            and float(candidate_window.reveal_start) > float(window.reveal_start) + 1e-9
                            and not same_precise_trigger(activation, candidate_activation)
                        ),
                        default=None,
                    ) if window is not None else None,
                ))
                if delta > self._SYNC_TOLERANCE_SECONDS + 1e-9:
                    violations.append(
                        f"{beat.id}:{activation.asset_id}:settle_delta={delta:.3f}"
                    )
                semantic_focus = cue.params.get("semantic_focus", {})
                trusted_attention = bool(
                    window is not None
                    and isinstance(semantic_focus, dict)
                    and semantic_focus.get("active") is True
                )
                if trusted_attention and actual_peak is not None:
                    expected_peak = float(window.semantic_peak)
                    if ordered_visual_unit:
                        try:
                            member_peak = float(cue.params["semantic_peak_time"])
                            if not (
                                isfinite(member_peak)
                                and cue.start <= member_peak <= settle
                            ):
                                raise ValueError("invalid member peak")
                            expected_peak = member_peak
                        except (KeyError, TypeError, ValueError, OverflowError):
                            expected_peak = cue.start + (
                                settle - cue.start
                            ) * (
                                (float(window.semantic_peak) - float(window.reveal_start))
                                / max(0.05, float(window.settle_at) - float(window.reveal_start))
                            )
                    focus_duration = settle - cue.start
                    peak_tolerance = max(
                        2.0 / 30.0,
                        min(0.12, focus_duration * 0.35),
                    )
                    peak_delta = actual_peak - expected_peak
                    if peak_delta < -peak_tolerance - 1e-9:
                        violations.append(
                            f"{beat.id}:{activation.asset_id}:focus_peak_too_early:"
                            f"role={semantic_focus.get('semantic_role') or semantic_focus.get('role') or 'UNKNOWN'}:"
                            f"target={expected_peak:.3f}:"
                            f"actual_peak={actual_peak:.3f}:tolerance={peak_tolerance:.3f}"
                        )
                    elif peak_delta > peak_tolerance + 1e-9:
                        violations.append(
                            f"{beat.id}:{activation.asset_id}:focus_peak_too_late:"
                            f"role={semantic_focus.get('semantic_role') or semantic_focus.get('role') or 'UNKNOWN'}:"
                            f"target={expected_peak:.3f}:"
                            f"actual_peak={actual_peak:.3f}:tolerance={peak_tolerance:.3f}"
                        )

            # Strong attention must be handed off before the next distinct spoken
            # meaning.  A gap after the last available activation is a legitimate
            # quiet hold; a gap while a later precise activation exists is not.
            ordered_trusted = sorted(
                trusted_windows,
                key=lambda row: (float(row[1].reveal_start), row[0].asset_id),
            )
            cohort_threshold = 2.0 / 30.0
            cohorts: list[list[tuple[AssetActivation, object]]] = []
            for row in ordered_trusted:
                if not cohorts:
                    cohorts.append([row])
                    continue
                anchor_window = cohorts[-1][0][1]
                same_moment = (
                    abs(float(row[1].reveal_start) - float(anchor_window.reveal_start))
                    <= cohort_threshold + 1e-9
                    and abs(float(row[1].phrase_start) - float(anchor_window.phrase_start))
                    <= cohort_threshold + 1e-9
                )
                if same_moment:
                    cohorts[-1].append(row)
                else:
                    cohorts.append([row])

            for cohort, next_cohort in zip(cohorts, cohorts[1:]):
                next_target = min(float(row[1].reveal_start) for row in next_cohort)
                next_cues = [
                    cues.get((beat.id, row[0].asset_id)) for row in next_cohort
                ]
                next_cues = [cue for cue in next_cues if cue is not None]
                if not next_cues:
                    continue
                next_cue = min(next_cues, key=lambda cue: cue.start)
                next_activation = next_cohort[0][0]
                for activation, window in cohort:
                    if same_precise_trigger(activation, next_activation):
                        continue
                    tolerance = max(
                        2.0 / 30.0,
                        min(
                            0.12,
                            (float(window.phrase_end) - float(window.phrase_start)) * 0.20,
                        ),
                    )
                    cue = cues.get((beat.id, activation.asset_id))
                    if cue is None:
                        continue
                    settle = float(cue.params.get("semantic_settle_time", cue.end))
                    current_focus = cue.params.get("semantic_focus", {})
                    next_focus = next_cue.params.get("semantic_focus", {})
                    semantic_role = (
                        str(
                            current_focus.get("semantic_role")
                            or current_focus.get("role")
                            or "UNKNOWN"
                        )
                        if isinstance(current_focus, dict)
                        else "UNKNOWN"
                    )
                    if settle > next_target + tolerance:
                        violations.append(
                            f"{beat.id}:{activation.asset_id}:settle_past_next_handoff:"
                            f"role={semantic_role}:"
                            f"target={float(window.reveal_start):.3f}:"
                            f"actual_reveal={cue.start:.3f}:actual_settle={settle:.3f}:"
                            f"next_target={next_target:.3f}"
                        )
                    if (
                        isinstance(current_focus, dict)
                        and isinstance(next_focus, dict)
                        and float(current_focus.get("strength", 0.0)) >= 0.60
                        and float(next_focus.get("strength", 0.0)) >= 0.60
                        and settle > next_cue.start + tolerance
                    ):
                        violations.append(
                            f"{beat.id}:{activation.asset_id}:strong_focus_overlap:"
                            f"actual_settle={settle:.3f}:next_reveal={next_cue.start:.3f}:"
                            f"next_asset={next_activation.asset_id}"
                        )

            for group_id, rows in sequence_motion.items():
                # Validate visual sequence only inside the exact same trigger cluster.
                # A semantic group may contain several precise narration spans whose
                # natural speech order legitimately conflicts with global sequence_order.
                # Story scheduling and QA intentionally share same_precise_trigger() so
                # the producer and validator cannot disagree about that authority.
                scheduled_rows = [row for row in rows if row[3]]
                clusters: list[
                    list[tuple[int, float, AssetActivation, bool]]
                ] = []
                for row in sorted(
                    scheduled_rows,
                    key=lambda item: (
                        float(item[2].spoken_start)
                        if item[2].spoken_start is not None
                        else float("inf"),
                        item[0],
                        item[2].asset_id,
                    ),
                ):
                    cluster = next(
                        (
                            candidate
                            for candidate in clusters
                            if candidate
                            and same_precise_trigger(candidate[0][2], row[2])
                        ),
                        None,
                    )
                    if cluster is None:
                        clusters.append([row])
                    else:
                        cluster.append(row)

                for cluster in clusters:
                    by_order: dict[
                        int,
                        list[tuple[float, AssetActivation]],
                    ] = {}
                    for order, start_time, activation, _scheduled in cluster:
                        by_order.setdefault(order, []).append(
                            (start_time, activation)
                        )
                    if len(by_order) <= 1:
                        continue
                    ordered_starts = [
                        (order, min(row[0] for row in by_order[order]))
                        for order in sorted(by_order)
                    ]
                    for (left_order, left_start), (right_order, right_start) in zip(
                        ordered_starts,
                        ordered_starts[1:],
                    ):
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
