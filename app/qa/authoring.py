from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from app.composition.text_director import TextPlacementDirector
from app.composition.occupancy import VisualOccupancyMap
from app.layout import ConstraintLayoutSolver
from app.layout.footprint import AlphaFootprintResolver
from app.models import (
    CompositionBeat,
    MotionCue,
    StoryBeat,
    TextCompositionBeat,
    TextPlan,
    Transcript,
    VisualAsset,
)
from app.reference import HexaVisualProfile
from app.shared.errors import StageFailedError
from app.text.timing.visibility import TextVisibilityPolicy


@dataclass(frozen=True, slots=True)
class AuthoringQAReport:
    layout_violations: tuple[str, ...]
    text_layout_violations: tuple[str, ...]
    short_directional_motion: tuple[str, ...]
    text_cue_count: int
    forced_alignment: bool

    @property
    def passed(self) -> bool:
        return not (
            self.layout_violations
            or self.text_layout_violations
            or self.short_directional_motion
        )


class AuthoringVisualQA:
    """Validate spatial contracts without redesigning the authored Final Package scene."""

    _TEXT_VISUAL_OVERLAP_LIMIT = 0.012
    _TEXT_TEXT_OVERLAP_LIMIT = 0.04

    def __init__(self, profile: HexaVisualProfile | None = None) -> None:
        self.profile = profile or HexaVisualProfile.production()
        self.layout = ConstraintLayoutSolver(self.profile)
        self.footprints = AlphaFootprintResolver()
        self.occupancy = VisualOccupancyMap()
        self.text_visibility = TextVisibilityPolicy()

    def inspect(
        self,
        *,
        transcript: Transcript,
        composition: list[CompositionBeat],
        motion: list[MotionCue],
        text: TextPlan,
        assets: list[VisualAsset],
        text_composition: list[TextCompositionBeat] | None = None,
        story: list[StoryBeat] | None = None,
        fps: int = 30,
    ) -> AuthoringQAReport:
        by_id = {asset.id: asset for asset in assets}
        layout_issues: list[str] = []
        for beat in composition:
            layout_issues.extend(
                f"{beat.beat_id}:{row}" for row in self.layout.inspect(beat.items, by_id)
            )

        text_issues = self._inspect_text_layout(
            composition=composition,
            story=story or [],
            text=text,
            text_composition=text_composition or [],
            assets=by_id,
        )

        short: list[str] = []
        minimum = self.profile.minimum_directional_frames / fps
        for cue in motion:
            program = cue.params.get("program") or {}
            keyframes = program.get("keyframes") or []
            directional = any(
                abs(float(frame.get("dx", 0.0))) > 1e-5
                or abs(float(frame.get("dy", 0.0))) > 1e-5
                for frame in keyframes
            )
            if directional and cue.end - cue.start + 1e-9 < minimum:
                short.append(f"{cue.beat_id}:{cue.asset_id}")

        return AuthoringQAReport(
            layout_violations=tuple(layout_issues),
            text_layout_violations=tuple(text_issues),
            short_directional_motion=tuple(short),
            text_cue_count=len(text.cues),
            forced_alignment=transcript.timing_source == "forced_alignment",
        )

    def _inspect_text_layout(
        self,
        *,
        composition: list[CompositionBeat],
        story: list[StoryBeat],
        text: TextPlan,
        text_composition: list[TextCompositionBeat],
        assets: dict[str, VisualAsset],
    ) -> list[str]:
        visual_by_beat = {row.beat_id: row for row in composition}
        beat_by_id = {row.id: row for row in story}
        cue_by_id = {cue.id: cue for cue in text.cues}
        cues_by_beat: dict[str, list] = {}
        for cue in text.cues:
            cues_by_beat.setdefault(cue.beat_id, []).append(cue)
        for rows in cues_by_beat.values():
            rows.sort(key=lambda cue: (cue.spoken_start, cue.id))
        issues: list[str] = []

        for text_beat in text_composition:
            visual = visual_by_beat.get(text_beat.beat_id)
            occupancy = (
                self.occupancy.build(visual.items, assets)
                if visual is not None
                else None
            )

            beat = beat_by_id.get(text_beat.beat_id)
            text_boxes: list[
                tuple[
                    str,
                    tuple[float, float, float, float],
                    float,
                    float,
                ]
            ] = []
            for item in text_beat.items:
                cue = cue_by_id.get(item.text_cue_id)
                if cue is None:
                    continue
                _, height = TextPlacementDirector.estimated_box(cue, scale=item.font_scale)
                box = (
                    item.x - item.max_width / 2,
                    item.y - height / 2,
                    item.x + item.max_width / 2,
                    item.y + height / 2,
                )
                if box[0] < 0.0 or box[1] < 0.0 or box[2] > 1.0 or box[3] > 1.0:
                    issues.append(f"{text_beat.beat_id}:text_offscreen:{item.text_cue_id}")
                visual_overlap = (
                    self.occupancy.overlap(occupancy, box).ratio
                    if occupancy is not None
                    else 0.0
                )
                if visual_overlap > self._TEXT_VISUAL_OVERLAP_LIMIT:
                    issues.append(
                        f"{text_beat.beat_id}:text_visual_overlap:{item.text_cue_id}:"
                        f"{visual_overlap:.3f}"
                    )
                visible_end = (
                    self.text_visibility.visible_end(
                        cue,
                        beat,
                        cues_by_beat.get(text_beat.beat_id, []),
                    )
                    if beat is not None
                    else cue.spoken_end
                )
                text_boxes.append(
                    (
                        item.text_cue_id,
                        box,
                        cue.spoken_start,
                        visible_end,
                    )
                )

            for index, (left_id, left_box, left_start, left_end) in enumerate(text_boxes):
                for right_id, right_box, right_start, right_end in text_boxes[index + 1:]:
                    if not self.text_visibility.overlaps(
                        left_start,
                        left_end,
                        right_start,
                        right_end,
                    ):
                        continue
                    ratio = max(
                        self._intersection_ratio(left_box, right_box),
                        self._intersection_ratio(right_box, left_box),
                    )
                    if ratio > self._TEXT_TEXT_OVERLAP_LIMIT:
                        issues.append(
                            f"{text_beat.beat_id}:text_text_overlap:{left_id}:{right_id}:"
                            f"{ratio:.3f}:time={max(left_start, right_start):.3f}-"
                            f"{min(left_end, right_end):.3f}"
                        )
        return issues

    @staticmethod
    def _intersection_ratio(
        left: tuple[float, float, float, float],
        right: tuple[float, float, float, float],
    ) -> float:
        x0 = max(left[0], right[0])
        y0 = max(left[1], right[1])
        x1 = min(left[2], right[2])
        y1 = min(left[3], right[3])
        if x1 <= x0 or y1 <= y0:
            return 0.0
        overlap = (x1 - x0) * (y1 - y0)
        area = max(1e-9, (left[2] - left[0]) * (left[3] - left[1]))
        return overlap / area

    @staticmethod
    def require(report: AuthoringQAReport, *, require_text: bool = False) -> None:
        if require_text and report.forced_alignment and report.text_cue_count == 0:
            raise StageFailedError(
                "required text layer produced no narration-locked cues",
                details={"code": "TEXT_LAYER_MISSING"},
            )
        if report.layout_violations:
            raise StageFailedError(
                "authored visual geometry is invalid",
                details={
                    "code": "LAYOUT_REFERENCE_VIOLATION",
                    "violations": list(report.layout_violations[:20]),
                },
            )
        if report.text_layout_violations:
            raise StageFailedError(
                "text placement overlaps authored visual geometry",
                details={
                    "code": "TEXT_LAYOUT_REFERENCE_VIOLATION",
                    "violations": list(report.text_layout_violations[:20]),
                },
            )
        if report.short_directional_motion:
            raise StageFailedError(
                "directional motion is shorter than the HEXA reference minimum",
                details={
                    "code": "MOTION_REFERENCE_VIOLATION",
                    "cues": list(report.short_directional_motion[:20]),
                },
            )

    @staticmethod
    def write(report: AuthoringQAReport, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = asdict(report)
        payload["passed"] = report.passed
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path
