from __future__ import annotations

import json
from collections import OrderedDict
from dataclasses import asdict, dataclass
from pathlib import Path

import cv2
import numpy as np

from app.models import LayoutItem, MotionSegment, RenderPlan
from app.motion.timing import (
    GOLDEN_MINOR,
    max_comfort_displacement,
    motion_comfort,
    projected_motion_activity_px,
    semantic_readability_duration,
    semantic_readability_floor,
    semantic_readability_floor_px,
)
from app.shared.errors import StageFailedError


@dataclass(frozen=True, slots=True)
class RenderedMotionViolation:
    code: str
    beat_id: str
    asset_id: str
    phase: str
    detail: str
    mean_delta: float = 0.0
    changed_ratio: float = 0.0


@dataclass(frozen=True, slots=True)
class RenderedMotionReport:
    checked_segments: int
    skipped_static_segments: int
    violations: tuple[RenderedMotionViolation, ...]

    @property
    def ok(self) -> bool:
        return not self.violations


@dataclass(slots=True)
class _RenderedEvidenceWork:
    beat_id: str
    asset_id: str
    phase: str
    segment_start: float
    segment_end: float
    item: LayoutItem
    expected_px: float
    baseline_index: int
    candidate_indices: tuple[int, ...]
    baseline_frame_seen: bool = False
    baseline_gray: np.ndarray | None = None
    decoded_candidates: int = 0
    roi_valid: bool = False
    best_mean: float = 0.0
    best_ratio: float = 0.0


class RenderedMotionQA:
    """Verify that semantic Motion segments actually survive FFmpeg encoding.

    Structural QA proves the timeline is correct. This pass samples the encoded MP4 in
    the authored asset ROI and requires visible frame change for every non-trivial
    INTERACT/REACT/PAYOFF segment. Together they catch the failure mode where metadata
    says an interaction exists but the rendered video remains static.
    """

    _PHASES = {"ENTRY", "ESTABLISH", "ADD", "INTERACT", "REACT", "PAYOFF", "EXIT"}
    # A decoded 1920x1080 BGR frame is ~6 MiB. An unbounded cache across a long
    # production video can therefore consume several GiB and be OOM-killed even
    # though the renderer itself is healthy. Keep only the small working set around
    # the currently inspected semantic segments.
    _FRAME_CACHE_LIMIT = 12

    def inspect(self, *, video: Path, plan: RenderPlan) -> RenderedMotionReport:
        if not video.is_file() or video.stat().st_size == 0:
            raise StageFailedError("rendered motion QA video is missing")

        layouts = {
            (beat.beat_id, item.asset_id): item
            for beat in plan.composition
            for item in beat.items
        }
        story = {beat.id: beat for beat in plan.story}
        checked = 0
        skipped = 0
        violations: list[RenderedMotionViolation] = []
        evidence_work: list[_RenderedEvidenceWork] = []

        # Phase 1 is metadata-only. Build every exact frame request before opening the
        # H.264 stream. The previous implementation random-seeked VideoCapture for every
        # segment/candidate pair; on long GOP production media that can repeatedly
        # decode from an earlier keyframe and make QA slower than rendering.
        for cue in plan.motion:
            item = layouts.get((cue.beat_id, cue.asset_id))
            beat = story.get(cue.beat_id)
            if item is None or beat is None:
                continue

            segments = list(cue.segments)
            if not segments and isinstance(cue.params, dict):
                # Standard Motion V3 cues render their base program directly when
                # there is no explicit semantic timeline. Those ENTRY gestures are
                # real encoded motion and must not sit outside encoded QA coverage.
                base_program = cue.params.get("program")
                keyframes = (
                    base_program.get("keyframes")
                    if isinstance(base_program, dict)
                    else None
                )
                if (
                    isinstance(keyframes, list)
                    and len(keyframes) >= 2
                    and float(cue.end) > float(cue.start) + 1e-9
                ):
                    qa_program = dict(base_program)
                    qa_program["qa_base_entry"] = True
                    focus = cue.params.get("semantic_focus") or {}
                    segments.append(MotionSegment(
                        phase="ENTRY",
                        start=float(cue.start),
                        end=float(cue.end),
                        program=qa_program,
                        semantic_event_id=focus.get("semantic_event_id"),
                    ))

            for segment in segments:
                if segment.phase not in self._PHASES:
                    continue
                duration = max(1e-6, float(segment.end) - float(segment.start))
                expected_px, peak_progress = self._expected_activity_px(
                    segment,
                    width=plan.width,
                    height=plan.height,
                    item_width=item.width,
                    item_height=item.height,
                )
                geometry_locked = (
                    isinstance(cue.params, dict)
                    and cue.params.get("render_constraints", {}).get("geometry_lock")
                    == "authored_footprint"
                )
                if geometry_locked:
                    skipped += 1
                    continue

                program_name = str(segment.program.get("name") or "")
                collision_limited = bool(segment.program.get("collision_limited"))
                qa_base_entry = bool(segment.program.get("qa_base_entry"))
                enforce_floor = (
                    "compound_unit" not in program_name
                    and not collision_limited
                    and not qa_base_entry
                )
                enforce_speed = "compound_unit" not in program_name

                try:
                    semantic_active_duration = float(
                        segment.program.get("semantic_active_duration", duration)
                    )
                except (TypeError, ValueError):
                    semantic_active_duration = duration
                readability_duration = semantic_readability_duration(
                    segment.phase,
                    segment_duration=duration,
                    active_duration=semantic_active_duration,
                )

                if enforce_floor and segment.phase in {"INTERACT", "REACT", "PAYOFF"}:
                    normalized_activity = self._expected_activity_normalized(
                        segment,
                        item_width=item.width,
                        item_height=item.height,
                    )
                    normalized_floor = semantic_readability_floor(
                        segment.phase,
                        item_width=item.width,
                        item_height=item.height,
                        duration=readability_duration,
                    )
                    if normalized_activity + 1e-9 < normalized_floor:
                        violations.append(RenderedMotionViolation(
                            code="MOTION_BELOW_PERCEPTUAL_FLOOR",
                            beat_id=cue.beat_id,
                            asset_id=cue.asset_id,
                            phase=segment.phase,
                            detail=(
                                f"expected normalized motion {normalized_activity:.5f} "
                                f"is below shared readability floor {normalized_floor:.5f}"
                            ),
                        ))
                        continue
                elif enforce_floor:
                    floor_px = self._perceptual_floor_px(
                        phase=segment.phase,
                        width=plan.width,
                        item_width=item.width,
                        item_height=item.height,
                        height=plan.height,
                        duration=readability_duration,
                    )
                    if expected_px + 1e-6 < floor_px:
                        violations.append(RenderedMotionViolation(
                            code="MOTION_BELOW_PERCEPTUAL_FLOOR",
                            beat_id=cue.beat_id,
                            asset_id=cue.asset_id,
                            phase=segment.phase,
                            detail=(
                                f"expected motion {expected_px:.2f}px is below readable "
                                f"floor {floor_px:.2f}px"
                            ),
                        ))
                        continue

                if enforce_speed:
                    normalized_speed = self._max_normalized_keyframe_speed(
                        segment,
                        duration=duration,
                        item_width=item.width,
                        item_height=item.height,
                    )
                    speed_limit = motion_comfort(segment.phase).max_normalized_speed * 1.08
                    if normalized_speed > speed_limit + 1e-6:
                        violations.append(RenderedMotionViolation(
                            code="MOTION_TOO_FAST",
                            beat_id=cue.beat_id,
                            asset_id=cue.asset_id,
                            phase=segment.phase,
                            detail=(
                                f"expected normalized peak speed {normalized_speed:.4f}/s "
                                f"exceeds comfort limit {speed_limit:.4f}/s"
                            ),
                        ))
                        continue

                if expected_px < 0.75:
                    skipped += 1
                    continue

                checked += 1
                baseline_time = (
                    max(float(beat.start), float(segment.start))
                    if segment.phase == "ENTRY"
                    else max(
                        float(beat.start),
                        float(segment.start) - max(2.0 / plan.fps, 0.045),
                    )
                )
                baseline_index = max(0, round(baseline_time * plan.fps))
                candidate_indices: list[int] = []
                for progress_value in self._evidence_progresses(segment, peak_progress):
                    candidate_time = min(
                        float(segment.end) - 0.5 / plan.fps,
                        float(segment.start) + duration * progress_value,
                    )
                    if candidate_time <= baseline_time + 0.25 / plan.fps:
                        continue
                    candidate_index = max(0, round(candidate_time * plan.fps))
                    if (
                        candidate_index > baseline_index
                        and candidate_index not in candidate_indices
                    ):
                        candidate_indices.append(candidate_index)

                evidence_work.append(_RenderedEvidenceWork(
                    beat_id=cue.beat_id,
                    asset_id=cue.asset_id,
                    phase=segment.phase,
                    segment_start=float(segment.start),
                    segment_end=float(segment.end),
                    item=item,
                    expected_px=expected_px,
                    baseline_index=baseline_index,
                    candidate_indices=tuple(sorted(candidate_indices)),
                ))

        # Phase 2 decodes the encoded video once in frame order. Only requested frames
        # are retrieved into BGR; all other frames use grab(), which keeps H.264 decode
        # linear and bounded while preserving the exact evidence frames and thresholds.
        if evidence_work:
            self._inspect_encoded_evidence(
                video=video,
                evidence_work=evidence_work,
                violations=violations,
            )

        return RenderedMotionReport(
            checked_segments=checked,
            skipped_static_segments=skipped,
            violations=tuple(violations),
        )

    @classmethod
    def _inspect_encoded_evidence(
        cls,
        *,
        video: Path,
        evidence_work: list[_RenderedEvidenceWork],
        violations: list[RenderedMotionViolation],
    ) -> None:
        capture = cv2.VideoCapture(str(video))
        if not capture.isOpened():
            raise StageFailedError("rendered motion QA cannot open encoded video")

        requests: dict[int, list[tuple[int, bool]]] = {}
        for work_index, work in enumerate(evidence_work):
            requests.setdefault(work.baseline_index, []).append((work_index, True))
            for frame_index in work.candidate_indices:
                requests.setdefault(frame_index, []).append((work_index, False))

        requested_indices = sorted(requests)
        if not requested_indices:
            capture.release()
            return

        first_index = requested_indices[0]
        last_index = requested_indices[-1]
        if first_index > 0:
            capture.set(cv2.CAP_PROP_POS_FRAMES, first_index)

        try:
            for frame_index in range(first_index, last_index + 1):
                ok = capture.grab()
                if not ok:
                    break
                frame_requests = requests.get(frame_index)
                if not frame_requests:
                    continue
                ok, frame = capture.retrieve()
                if not ok or frame is None:
                    continue

                # Baselines are always authored earlier than their candidates, but a
                # single encoded frame may be shared by unrelated work items. Process
                # baseline requests first so each work item is deterministic.
                for work_index, baseline in sorted(
                    frame_requests, key=lambda row: (not row[1], row[0])
                ):
                    work = evidence_work[work_index]
                    if baseline:
                        work.baseline_frame_seen = True
                        crop = cls._crop(
                            frame,
                            item=work.item,
                            expected_px=work.expected_px,
                        )
                        if crop.size:
                            work.baseline_gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
                        continue

                    work.decoded_candidates += 1
                    if work.baseline_gray is None:
                        continue
                    crop = cls._crop(
                        frame,
                        item=work.item,
                        expected_px=work.expected_px,
                    )
                    if crop.size == 0:
                        continue
                    gray_candidate = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
                    if gray_candidate.shape != work.baseline_gray.shape:
                        continue
                    work.roi_valid = True
                    delta = cv2.absdiff(work.baseline_gray, gray_candidate)
                    work.best_mean = max(work.best_mean, float(np.mean(delta)))
                    work.best_ratio = max(
                        work.best_ratio,
                        float(np.mean(delta >= 8)),
                    )
        finally:
            capture.release()

        for work in evidence_work:
            if not work.baseline_frame_seen:
                violations.append(RenderedMotionViolation(
                    code="RENDERED_SEGMENT_FRAME_MISSING",
                    beat_id=work.beat_id,
                    asset_id=work.asset_id,
                    phase=work.phase,
                    detail=(
                        "could not decode baseline evidence frame around "
                        f"{work.segment_start:.3f}-{work.segment_end:.3f}s"
                    ),
                ))
                continue
            if work.decoded_candidates == 0:
                violations.append(RenderedMotionViolation(
                    code="RENDERED_SEGMENT_FRAME_MISSING",
                    beat_id=work.beat_id,
                    asset_id=work.asset_id,
                    phase=work.phase,
                    detail=(
                        "could not decode candidate evidence frames around "
                        f"{work.segment_start:.3f}-{work.segment_end:.3f}s"
                    ),
                ))
                continue
            if not work.roi_valid:
                violations.append(RenderedMotionViolation(
                    code="RENDERED_SEGMENT_ROI_EMPTY",
                    beat_id=work.beat_id,
                    asset_id=work.asset_id,
                    phase=work.phase,
                    detail="authored Composition ROI produced no encoded pixels",
                ))
                continue
            if work.best_mean < 0.35 and work.best_ratio < 0.0015:
                violations.append(RenderedMotionViolation(
                    code="RENDERED_SEGMENT_INACTIVE",
                    beat_id=work.beat_id,
                    asset_id=work.asset_id,
                    phase=work.phase,
                    detail=(
                        f"timeline expects ~{work.expected_px:.2f}px semantic motion "
                        "but encoded ROI is effectively static"
                    ),
                    mean_delta=work.best_mean,
                    changed_ratio=work.best_ratio,
                ))

    @classmethod
    def _remember_frame(
        cls,
        cache: OrderedDict[int, np.ndarray],
        index: int,
        frame: np.ndarray,
    ) -> None:
        cache[index] = frame
        while len(cache) > cls._FRAME_CACHE_LIMIT:
            cache.popitem(last=False)


    @staticmethod
    def _evidence_progresses(
        segment: MotionSegment,
        expected_peak: float,
    ) -> tuple[float, ...]:
        """Sample several legal points so frame quantization cannot hide real motion."""
        values = [expected_peak, 0.25, 0.50, 0.75, 0.90]
        keyframes = segment.program.get("keyframes")
        if isinstance(keyframes, list):
            for frame in keyframes:
                try:
                    values.append(float(frame.get("progress", 0.5)))
                except (TypeError, ValueError):
                    continue
        output: list[float] = []
        for value in values:
            clipped = max(0.08, min(0.94, float(value)))
            if not any(abs(clipped - existing) < 0.02 for existing in output):
                output.append(clipped)
        return tuple(output)



    @staticmethod
    def _expected_activity_normalized(
        segment: MotionSegment,
        *,
        item_width: float,
        item_height: float,
    ) -> float:
        """Measure authored semantic activity in Planner's Composition-space units."""
        keyframes = segment.program.get("keyframes")
        if not isinstance(keyframes, list) or not keyframes:
            return 0.0
        asset_extent = max(1e-6, min(float(item_width), float(item_height)))
        best = 0.0
        for frame in keyframes:
            if not isinstance(frame, dict):
                continue
            try:
                translation = float(np.hypot(
                    float(frame.get("dx", 0.0)),
                    float(frame.get("dy", 0.0)),
                ))
                scale = abs(float(frame.get("scale", 1.0)) - 1.0) * asset_extent
            except (TypeError, ValueError):
                continue
            best = max(best, translation, scale)
        return best

    @staticmethod
    def _directional_comfort_budget_px(
        segment: MotionSegment,
        *,
        duration: float,
        width: int,
        height: int,
        item_width: float,
        item_height: float,
    ) -> float:
        """Translate the normalized comfort ceiling into this gesture's pixel axis.

        MotionPlanner caps translation in normalized Composition space. A diagonal or
        vertical gesture therefore has a different pixel budget than a horizontal one
        on a non-square canvas. Scale has its own asset-size projection. QA must use
        the same geometry or it can demand a pixel floor that Planner cannot reach
        without violating the speed ceiling.
        """
        keyframes = segment.program.get("keyframes")
        if not isinstance(keyframes, list) or not keyframes:
            return 0.0
        if segment.phase in {"INTERACT", "REACT", "PAYOFF"}:
            comfort_seconds = duration * GOLDEN_MINOR
        else:
            comfort_seconds = duration
        normalized_budget = max_comfort_displacement(
            segment.phase,
            comfort_seconds,
        )
        if normalized_budget <= 0.0:
            return 0.0

        translation_factor = 0.0
        translation_peak_px = 0.0
        asset_extent = max(1e-6, min(float(item_width), float(item_height)))
        asset_px = max(1.0, min(width * item_width, height * item_height))
        scale_peak_px = 0.0

        for frame in keyframes:
            if not isinstance(frame, dict):
                continue
            try:
                dx = float(frame.get("dx", 0.0))
                dy = float(frame.get("dy", 0.0))
                scale_delta = abs(float(frame.get("scale", 1.0)) - 1.0)
            except (TypeError, ValueError):
                continue

            magnitude = float(np.hypot(dx, dy))
            if magnitude > 1e-9:
                projected_px = float(np.hypot(dx * width, dy * height))
                if projected_px > translation_peak_px:
                    translation_peak_px = projected_px
                    translation_factor = projected_px / magnitude
            scale_peak_px = max(scale_peak_px, scale_delta * asset_px)

        # Use the pixel projection of the motion channel that actually dominates the
        # authored gesture. Taking max(translation_factor, scale_factor) merely because
        # a small scale pulse also exists can overstate the reachable readability
        # budget for a vertical/diagonal REACT on a 16:9 canvas.
        if translation_peak_px >= scale_peak_px and translation_factor > 0.0:
            pixel_factor = translation_factor
        elif scale_peak_px > 0.0:
            pixel_factor = asset_px / asset_extent
        else:
            pixel_factor = translation_factor

        return normalized_budget * pixel_factor if pixel_factor > 0.0 else 0.0

    @staticmethod
    def _max_normalized_keyframe_speed(
        segment: MotionSegment,
        *,
        duration: float,
        item_width: float,
        item_height: float,
    ) -> float:
        """Measure the same normalized velocity budget enforced by MotionPlanner.

        Comparing planner-normalized motion against a width-only pixel ceiling creates
        false failures for diagonal movement, portrait assets and scale pulses. Use
        the canonical Composition-space contract instead: translation magnitude plus
        scale converted through the asset's normalized extent.
        """
        keyframes = segment.program.get("keyframes")
        if not isinstance(keyframes, list) or len(keyframes) < 2:
            return 0.0
        asset_extent = max(1e-6, min(float(item_width), float(item_height)))
        rows: list[tuple[float, float, float, float]] = []
        for frame in keyframes:
            try:
                rows.append((
                    float(frame.get("progress", 0.0)),
                    float(frame.get("dx", 0.0)),
                    float(frame.get("dy", 0.0)),
                    float(frame.get("scale", 1.0)),
                ))
            except (TypeError, ValueError):
                continue
        rows.sort(key=lambda row: row[0])
        peak_speed = 0.0
        for left, right in zip(rows, rows[1:]):
            seconds = max(1e-6, (right[0] - left[0]) * duration)
            translation = float(np.hypot(
                right[1] - left[1],
                right[2] - left[2],
            ))
            scale_motion = abs(right[3] - left[3]) * asset_extent
            peak_speed = max(
                peak_speed,
                max(translation, scale_motion) / seconds,
            )
        return peak_speed

    @staticmethod
    def _max_keyframe_speed_px(
        segment: MotionSegment,
        *,
        duration: float,
        width: int,
        height: int,
        item_width: float,
        item_height: float,
    ) -> float:
        keyframes = segment.program.get("keyframes")
        if not isinstance(keyframes, list) or len(keyframes) < 2:
            return 0.0
        asset_px = max(1.0, min(width * item_width, height * item_height))
        rows: list[tuple[float, float, float, float]] = []
        for frame in keyframes:
            try:
                rows.append((
                    float(frame.get("progress", 0.0)),
                    float(frame.get("dx", 0.0)),
                    float(frame.get("dy", 0.0)),
                    float(frame.get("scale", 1.0)),
                ))
            except (TypeError, ValueError):
                continue
        rows.sort(key=lambda row: row[0])
        peak_speed = 0.0
        for left, right in zip(rows, rows[1:]):
            seconds = max(1e-6, (right[0] - left[0]) * duration)
            translation_px = float(np.hypot(
                (right[1] - left[1]) * width,
                (right[2] - left[2]) * height,
            ))
            travel_px = max(
                translation_px,
                abs(right[3] - left[3]) * asset_px,
            )
            peak_speed = max(peak_speed, travel_px / seconds)
        return peak_speed

    @staticmethod
    def _perceptual_floor_px(
        *,
        phase: str,
        width: int,
        height: int,
        item_width: float,
        item_height: float,
        duration: float,
    ) -> float:
        """Project the shared planner readability contract into encoded pixels."""
        return semantic_readability_floor_px(
            phase,
            item_width=item_width,
            item_height=item_height,
            duration=duration,
            frame_width=width,
            frame_height=height,
        )

    @staticmethod
    def _expected_activity_px(
        segment: MotionSegment,
        *,
        width: int,
        height: int,
        item_width: float,
        item_height: float,
    ) -> tuple[float, float]:
        keyframes = segment.program.get("keyframes")
        if not isinstance(keyframes, list) or not keyframes:
            return 0.0, 0.5
        best_px = 0.0
        best_progress = 0.5
        for frame in keyframes:
            try:
                dx = float(frame.get("dx", 0.0))
                dy = float(frame.get("dy", 0.0))
                scale = float(frame.get("scale", 1.0))
                progress = float(frame.get("progress", 0.5))
            except (TypeError, ValueError):
                continue
            activity = projected_motion_activity_px(
                dx=dx,
                dy=dy,
                scale=scale,
                item_width=item_width,
                item_height=item_height,
                frame_width=width,
                frame_height=height,
            )
            if activity > best_px:
                best_px = activity
                best_progress = max(0.05, min(0.95, progress))
        return best_px, best_progress

    @staticmethod
    def _crop(frame: np.ndarray, *, item: LayoutItem, expected_px: float) -> np.ndarray:
        height, width = frame.shape[:2]
        cx = float(item.x) * width
        cy = float(item.y) * height
        box_w = float(item.width) * width
        box_h = float(item.height) * height
        margin = max(8.0, expected_px * 2.5)
        left = max(0, int(cx - box_w / 2 - margin))
        right = min(width, int(cx + box_w / 2 + margin))
        top = max(0, int(cy - box_h / 2 - margin))
        bottom = min(height, int(cy + box_h / 2 + margin))
        return frame[top:bottom, left:right]

    @staticmethod
    def _crop_pair(
        before: np.ndarray,
        peak: np.ndarray,
        *,
        item: LayoutItem,
        expected_px: float,
    ) -> tuple[np.ndarray, np.ndarray]:
        return (
            RenderedMotionQA._crop(before, item=item, expected_px=expected_px),
            RenderedMotionQA._crop(peak, item=item, expected_px=expected_px),
        )

    @staticmethod
    def write(report: RenderedMotionReport, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({
                "ok": report.ok,
                "checked_segments": report.checked_segments,
                "skipped_static_segments": report.skipped_static_segments,
                "violations": [asdict(row) for row in report.violations],
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def require(report: RenderedMotionReport) -> None:
        if report.ok:
            return
        raise StageFailedError(
            "rendered semantic motion QA failed",
            details={
                "violation_count": len(report.violations),
                "violations": [asdict(row) for row in report.violations[:12]],
            },
        )