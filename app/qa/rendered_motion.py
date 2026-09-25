from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

import cv2
import numpy as np

from app.models import MotionSegment, RenderPlan
from app.motion.timing import (
    GOLDEN_MINOR,
    comfort_gain,
    max_comfort_displacement,
    motion_comfort,
    semantic_readability_floor,
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


class RenderedMotionQA:
    """Verify that semantic Motion segments actually survive FFmpeg encoding.

    Structural QA proves the timeline is correct. This pass samples the encoded MP4 in
    the authored asset ROI and requires visible frame change for every non-trivial
    INTERACT/REACT/PAYOFF segment. Together they catch the failure mode where metadata
    says an interaction exists but the rendered video remains static.
    """

    _PHASES = {"ENTRY", "INTERACT", "REACT", "PAYOFF", "EXIT"}

    def inspect(self, *, video: Path, plan: RenderPlan) -> RenderedMotionReport:
        if not video.is_file() or video.stat().st_size == 0:
            raise StageFailedError("rendered motion QA video is missing")

        capture = cv2.VideoCapture(str(video))
        if not capture.isOpened():
            raise StageFailedError("rendered motion QA cannot open encoded video")

        layouts = {
            (beat.beat_id, item.asset_id): item
            for beat in plan.composition
            for item in beat.items
        }
        story = {beat.id: beat for beat in plan.story}
        frame_cache: dict[int, np.ndarray] = {}
        checked = 0
        skipped = 0
        violations: list[RenderedMotionViolation] = []

        def frame_at(index: int) -> np.ndarray | None:
            index = max(0, index)
            if index in frame_cache:
                return frame_cache[index]
            capture.set(cv2.CAP_PROP_POS_FRAMES, index)
            ok, frame = capture.read()
            if not ok or frame is None:
                return None
            frame_cache[index] = frame
            return frame

        try:
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
                    # Mark the synthetic QA segment so intentional attention-damped
                    # support/context entries are checked for actual pixels + speed
                    # without being judged against a second full-strength floor.
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
                        # Renderer intentionally suppresses translation/scale for these
                        # family-canvas members. Requiring encoded transform activity
                        # here contradicts the render contract and creates a false hard
                        # failure. Visibility/timing remains covered by StorySync and
                        # scene-continuity QA.
                        skipped += 1
                        continue
                    program_name = str(segment.program.get("name") or "")
                    collision_limited = bool(segment.program.get("collision_limited"))
                    qa_base_entry = bool(segment.program.get("qa_base_entry"))
                    enforce_floor = (
                        not geometry_locked
                        and "compound_unit" not in program_name
                        and not collision_limited
                        and not qa_base_entry
                    )
                    enforce_speed = (
                        not geometry_locked
                        and "compound_unit" not in program_name
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
                            duration=duration,
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
                            duration=duration,
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
                        speed_limit = (
                            motion_comfort(segment.phase).max_normalized_speed * 1.08
                        )
                        if normalized_speed > speed_limit + 1e-6:
                            violations.append(RenderedMotionViolation(
                                code="MOTION_TOO_FAST",
                                beat_id=cue.beat_id,
                                asset_id=cue.asset_id,
                                phase=segment.phase,
                                detail=(
                                    f"expected normalized peak speed "
                                    f"{normalized_speed:.4f}/s exceeds comfort limit "
                                    f"{speed_limit:.4f}/s"
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
                    before = frame_at(round(baseline_time * plan.fps))
                    if before is None:
                        violations.append(RenderedMotionViolation(
                            code="RENDERED_SEGMENT_FRAME_MISSING",
                            beat_id=cue.beat_id,
                            asset_id=cue.asset_id,
                            phase=segment.phase,
                            detail=(
                                f"could not decode baseline evidence frame around "
                                f"{segment.start:.3f}-{segment.end:.3f}s"
                            ),
                        ))
                        continue

                    evidence_progress = self._evidence_progresses(segment, peak_progress)
                    best_mean = 0.0
                    best_ratio = 0.0
                    decoded_candidates = 0
                    roi_valid = False
                    for progress_value in evidence_progress:
                        candidate_time = min(
                            float(segment.end) - 0.5 / plan.fps,
                            float(segment.start) + duration * progress_value,
                        )
                        if candidate_time <= baseline_time + 0.25 / plan.fps:
                            continue
                        candidate = frame_at(round(candidate_time * plan.fps))
                        if candidate is None:
                            continue
                        decoded_candidates += 1
                        crop_before, crop_candidate = self._crop_pair(
                            before,
                            candidate,
                            item=item,
                            expected_px=expected_px,
                        )
                        if crop_before.size == 0 or crop_candidate.size == 0:
                            continue
                        roi_valid = True
                        gray_before = cv2.cvtColor(crop_before, cv2.COLOR_BGR2GRAY)
                        gray_candidate = cv2.cvtColor(crop_candidate, cv2.COLOR_BGR2GRAY)
                        delta = cv2.absdiff(gray_before, gray_candidate)
                        best_mean = max(best_mean, float(np.mean(delta)))
                        best_ratio = max(best_ratio, float(np.mean(delta >= 8)))

                    if decoded_candidates == 0:
                        violations.append(RenderedMotionViolation(
                            code="RENDERED_SEGMENT_FRAME_MISSING",
                            beat_id=cue.beat_id,
                            asset_id=cue.asset_id,
                            phase=segment.phase,
                            detail=(
                                f"could not decode candidate evidence frames around "
                                f"{segment.start:.3f}-{segment.end:.3f}s"
                            ),
                        ))
                        continue
                    if not roi_valid:
                        violations.append(RenderedMotionViolation(
                            code="RENDERED_SEGMENT_ROI_EMPTY",
                            beat_id=cue.beat_id,
                            asset_id=cue.asset_id,
                            phase=segment.phase,
                            detail="authored Composition ROI produced no encoded pixels",
                        ))
                        continue

                    # H.264 noise on a static white-backed frame is far below these
                    # thresholds. A genuine 1px+ transform changes edge occupancy by
                    # materially more, even for small sparse icons.
                    if best_mean < 0.35 and best_ratio < 0.0015:
                        violations.append(RenderedMotionViolation(
                            code="RENDERED_SEGMENT_INACTIVE",
                            beat_id=cue.beat_id,
                            asset_id=cue.asset_id,
                            phase=segment.phase,
                            detail=(
                                f"timeline expects ~{expected_px:.2f}px semantic motion "
                                "but encoded ROI is effectively static"
                            ),
                            mean_delta=best_mean,
                            changed_ratio=best_ratio,
                        ))
        finally:
            capture.release()

        return RenderedMotionReport(
            checked_segments=checked,
            skipped_static_segments=skipped,
            violations=tuple(violations),
        )




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
        ratios = {
            "ENTRY": 0.010,
            "INTERACT": 0.015,
            "REACT": 0.013,
            "PAYOFF": 0.009,
            "EXIT": 0.016,
        }
        ratio = ratios.get(phase, 0.0)
        if ratio <= 0:
            return 0.0
        asset_px = max(1.0, min(width * item_width, height * item_height))
        base = max(6.0, min(36.0, width * ratio, asset_px * 0.25))
        readable = base * comfort_gain(phase, duration)

        # Readability and comfort must form a satisfiable contract. Semantic
        # out-and-back accents have only the shorter golden leg (38.2%) to return
        # to Composition, so a short Story window may not physically support the
        # nominal pixel floor without exceeding the comfort-speed ceiling.
        if phase in {"INTERACT", "REACT", "PAYOFF"}:
            comfort_seconds = duration * GOLDEN_MINOR
        else:
            comfort_seconds = duration
        comfort_budget_px = width * max_comfort_displacement(
            phase,
            comfort_seconds,
        )
        if comfort_budget_px > 0.0:
            readable = min(readable, comfort_budget_px)
        return readable

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
        asset_px = max(1.0, min(width * item_width, height * item_height))
        for frame in keyframes:
            try:
                dx = float(frame.get("dx", 0.0)) * width
                dy = float(frame.get("dy", 0.0)) * height
                translation = float(np.hypot(dx, dy))
                scale = abs(float(frame.get("scale", 1.0)) - 1.0) * asset_px
                progress = float(frame.get("progress", 0.5))
            except (TypeError, ValueError):
                continue
            activity = max(translation, scale)
            if activity > best_px:
                best_px = activity
                best_progress = max(0.05, min(0.95, progress))
        return best_px, best_progress

    @staticmethod
    def _crop_pair(before: np.ndarray, peak: np.ndarray, *, item, expected_px: float):
        height, width = before.shape[:2]
        cx = float(item.x) * width
        cy = float(item.y) * height
        box_w = float(item.width) * width
        box_h = float(item.height) * height
        margin = max(8.0, expected_px * 2.5)
        left = max(0, int(cx - box_w / 2 - margin))
        right = min(width, int(cx + box_w / 2 + margin))
        top = max(0, int(cy - box_h / 2 - margin))
        bottom = min(height, int(cy + box_h / 2 + margin))
        return before[top:bottom, left:right], peak[top:bottom, left:right]

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
