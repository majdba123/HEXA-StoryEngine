from __future__ import annotations

from dataclasses import dataclass

from app.layout import ConstraintLayoutSolver
from app.models import CompositionBeat, MotionCue, TextPlan, Transcript, VisualAsset
from app.reference import HexaVisualProfile
from app.shared.errors import StageFailedError


@dataclass(frozen=True, slots=True)
class AuthoringQAReport:
    layout_violations: tuple[str, ...]
    short_directional_motion: tuple[str, ...]
    text_cue_count: int
    forced_alignment: bool

    @property
    def passed(self) -> bool:
        return not self.layout_violations and not self.short_directional_motion


class AuthoringVisualQA:
    def __init__(self, profile: HexaVisualProfile | None = None) -> None:
        self.profile = profile or HexaVisualProfile.production()
        self.layout = ConstraintLayoutSolver(self.profile)

    def inspect(
        self,
        *,
        transcript: Transcript,
        composition: list[CompositionBeat],
        motion: list[MotionCue],
        text: TextPlan,
        assets: list[VisualAsset],
        fps: int = 30,
    ) -> AuthoringQAReport:
        by_id = {asset.id: asset for asset in assets}
        layout_issues: list[str] = []
        for beat in composition:
            layout_issues.extend(f"{beat.beat_id}:{row}" for row in self.layout.inspect(beat.items, by_id))

        short: list[str] = []
        minimum = self.profile.minimum_directional_frames / fps
        for cue in motion:
            program = cue.params.get("program") or {}
            keyframes = program.get("keyframes") or []
            directional = any(
                abs(float(frame.get("dx", 0.0))) > 1e-5 or abs(float(frame.get("dy", 0.0))) > 1e-5
                for frame in keyframes
            )
            if directional and cue.end - cue.start + 1e-9 < minimum:
                short.append(f"{cue.beat_id}:{cue.asset_id}")

        return AuthoringQAReport(
            layout_violations=tuple(layout_issues),
            short_directional_motion=tuple(short),
            text_cue_count=len(text.cues),
            forced_alignment=transcript.timing_source == "forced_alignment",
        )

    @staticmethod
    def require(report: AuthoringQAReport, *, require_text: bool = False) -> None:
        if require_text and report.forced_alignment and report.text_cue_count == 0:
            raise StageFailedError(
                "required text layer produced no narration-locked cues",
                details={"code": "TEXT_LAYER_MISSING"},
            )
        if report.layout_violations:
            raise StageFailedError(
                "visual layout violates HEXA reference constraints",
                details={"code": "LAYOUT_REFERENCE_VIOLATION", "violations": list(report.layout_violations[:20])},
            )
        if report.short_directional_motion:
            raise StageFailedError(
                "directional motion is shorter than the HEXA reference minimum",
                details={"code": "MOTION_REFERENCE_VIOLATION", "cues": list(report.short_directional_motion[:20])},
            )
