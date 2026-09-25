from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

import cv2
import numpy as np

from app.models import MotionSegment, RenderPlan
from app.motion.timing import comfort_gain, motion_comfort
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
                for segment in cue.segments:
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
                    program_name = str(segment.program.get("name") or "")
                    enforce_floor = not geometry_locked and "compound_unit" not in program_name
                    floor_px = self._perceptual_floor_px(
                        phase=segment.phase,
                        width=plan.width,
                        item_width=item.width,
                        item_height=item.height,
                        height=plan.height,
                        duration=duration,
                    )
                    if enforce_floor and expected_px + 1e-6 < floor_px:
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
                    if enforce_floor:
                        speed_px = expected_px / duration
                        speed_limit_px = (
                            plan.width
                            * motion_comfort(segment.phase).max_normalized_speed
                            * 1.08
                        )
                        if speed_px > speed_limit_px + 1e-6:
                            violations.append(RenderedMotionViolation(
                                code="MOTION_TOO_FAST",
                                beat_id=cue.beat_id,
                                asset_id=cue.asset_id,
                                phase=segment.phase,
                                detail=(
                                    f"expected peak speed {speed_px:.1f}px/s exceeds "
                                    f"comfort limit {speed_limit_px:.1f}px/s"
                                ),
                            ))
                            continue
                    if expected_px < 0.75:
                        skipped += 1
                        continue

                    checked += 1
                    baseline_time = max(
                        float(beat.start),
                        float(segment.start) - max(2.0 / plan.fps, 0.045),
                    )
                    peak_time = min(
                        float(segment.end) - 1.0 / plan.fps,
                        float(segment.start) + duration * peak_progress,
                    )
                    if peak_time <= baseline_time + 1.0 / plan.fps:
                        peak_time = min(
                            float(segment.end) - 0.5 / plan.fps,
                            float(segment.start) + duration * 0.5,
                        )

                    before = frame_at(round(baseline_time * plan.fps))
                    peak = frame_at(round(peak_time * plan.fps))
                    if before is None or peak is None:
                        violations.append(RenderedMotionViolation(
                            code="RENDERED_SEGMENT_FRAME_MISSING",
                            beat_id=cue.beat_id,
                            asset_id=cue.asset_id,
                            phase=segment.phase,
                            detail=(
                                f"could not decode evidence frames around "
                                f"{segment.start:.3f}-{segment.end:.3f}s"
                            ),
                        ))
                        continue

                    crop_before, crop_peak = self._crop_pair(
                        before,
                        peak,
                        item=item,
                        expected_px=expected_px,
                    )
                    if crop_before.size == 0 or crop_peak.size == 0:
                        violations.append(RenderedMotionViolation(
                            code="RENDERED_SEGMENT_ROI_EMPTY",
                            beat_id=cue.beat_id,
                            asset_id=cue.asset_id,
                            phase=segment.phase,
                            detail="authored Composition ROI produced no encoded pixels",
                        ))
                        continue

                    gray_before = cv2.cvtColor(crop_before, cv2.COLOR_BGR2GRAY)
                    gray_peak = cv2.cvtColor(crop_peak, cv2.COLOR_BGR2GRAY)
                    delta = cv2.absdiff(gray_before, gray_peak)
                    mean_delta = float(np.mean(delta))
                    changed_ratio = float(np.mean(delta >= 8))

                    # H.264 noise on a static white-backed frame is far below these
                    # thresholds. A genuine 1px+ transform changes edge occupancy by
                    # materially more, even for small sparse icons.
                    if mean_delta < 0.35 and changed_ratio < 0.0015:
                        violations.append(RenderedMotionViolation(
                            code="RENDERED_SEGMENT_INACTIVE",
                            beat_id=cue.beat_id,
                            asset_id=cue.asset_id,
                            phase=segment.phase,
                            detail=(
                                f"timeline expects ~{expected_px:.2f}px semantic motion "
                                "but encoded ROI is effectively static"
                            ),
                            mean_delta=mean_delta,
                            changed_ratio=changed_ratio,
                        ))
        finally:
            capture.release()

        return RenderedMotionReport(
            checked_segments=checked,
            skipped_static_segments=skipped,
            violations=tuple(violations),
        )


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
        return base * comfort_gain(phase, duration)

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
                dx = abs(float(frame.get("dx", 0.0))) * width
                dy = abs(float(frame.get("dy", 0.0))) * height
                scale = abs(float(frame.get("scale", 1.0)) - 1.0) * asset_px
                progress = float(frame.get("progress", 0.5))
            except (TypeError, ValueError):
                continue
            activity = max(dx, dy, scale)
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
