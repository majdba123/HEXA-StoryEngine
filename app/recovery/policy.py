from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class FailureDisposition(StrEnum):
    PREVENT = "prevent"
    RECOVER = "recover"
    FAIL_FAST = "fail_fast"
    POST_RENDER_PROOF = "post_render_proof"


@dataclass(frozen=True, slots=True)
class FailurePolicy:
    code: str
    owner_stage: str
    disposition: FailureDisposition
    reason: str
    semantic_authority_change_allowed: bool = False


def _policy(
    code: str,
    owner_stage: str,
    disposition: FailureDisposition,
    reason: str,
) -> FailurePolicy:
    return FailurePolicy(
        code=code,
        owner_stage=owner_stage,
        disposition=disposition,
        reason=reason,
    )


HISTORICAL_FAILURE_POLICIES: dict[str, FailurePolicy] = {
    "INVALID_PACKAGE": _policy(
        "INVALID_PACKAGE",
        "input",
        FailureDisposition.FAIL_FAST,
        "Final Package semantic authority is malformed or incomplete",
    ),
    "FFMPEG_UNAVAILABLE": _policy(
        "FFMPEG_UNAVAILABLE",
        "input",
        FailureDisposition.FAIL_FAST,
        "Required render dependency is unavailable",
    ),
    "FFMPEG_FILTER_FILE_UNSUPPORTED": _policy(
        "FFMPEG_FILTER_FILE_UNSUPPORTED",
        "input",
        FailureDisposition.FAIL_FAST,
        "Installed FFmpeg cannot execute the production file-backed filter path",
    ),
    "FFMPEG_H264_ENCODER_UNAVAILABLE": _policy(
        "FFMPEG_H264_ENCODER_UNAVAILABLE",
        "input",
        FailureDisposition.FAIL_FAST,
        "Installed FFmpeg cannot encode the required H.264 output",
    ),
    "MISSING_RELATION_TIMELINE": _policy(
        "MISSING_RELATION_TIMELINE",
        "motion",
        FailureDisposition.PREVENT,
        "Motion must execute every authored relation timeline",
    ),
    "MISSING_TARGET_REACTION": _policy(
        "MISSING_TARGET_REACTION",
        "motion",
        FailureDisposition.PREVENT,
        "Required relation target reaction must be authored by MotionPlanner",
    ),
    "MISSING_RESULT_PAYOFF": _policy(
        "MISSING_RESULT_PAYOFF",
        "motion",
        FailureDisposition.PREVENT,
        "Required semantic result payoff must be authored by MotionPlanner",
    ),
    "SEGMENT_PAST_HANDOFF": _policy(
        "SEGMENT_PAST_HANDOFF",
        "motion",
        FailureDisposition.PREVENT,
        "Motion segments must settle before the Story-owned handoff boundary",
    ),
    "MOTION_CREATES_COLLISION": _policy(
        "MOTION_CREATES_COLLISION",
        "motion",
        FailureDisposition.PREVENT,
        "Motion feasibility/collision fitting must reject unsafe paths before render",
    ),
    "MOTION_TOO_FAST": _policy(
        "MOTION_TOO_FAST",
        "motion",
        FailureDisposition.PREVENT,
        "Planner must respect the shared motion comfort ceiling",
    ),
    "MOTION_BELOW_PERCEPTUAL_FLOOR": _policy(
        "MOTION_BELOW_PERCEPTUAL_FLOOR",
        "motion",
        FailureDisposition.PREVENT,
        "Planner must meet the shared encoded-pixel readability floor",
    ),
    "TERMINAL_EXIT_ON_PERSISTENT_ASSET": _policy(
        "TERMINAL_EXIT_ON_PERSISTENT_ASSET",
        "motion",
        FailureDisposition.PREVENT,
        "Persistent asset lifecycle cannot contain a terminal leave before continuation",
    ),
    "RENDERED_SEGMENT_INACTIVE": _policy(
        "RENDERED_SEGMENT_INACTIVE",
        "render",
        FailureDisposition.POST_RENDER_PROOF,
        "Encoded ROI is static despite an authored semantic motion segment",
    ),
    "RENDERED_SEGMENT_FRAME_MISSING": _policy(
        "RENDERED_SEGMENT_FRAME_MISSING",
        "render",
        FailureDisposition.POST_RENDER_PROOF,
        "Encoded evidence frames are missing and require diagnosis, not blind retry",
    ),
    "RENDERED_SEGMENT_ROI_EMPTY": _policy(
        "RENDERED_SEGMENT_ROI_EMPTY",
        "render",
        FailureDisposition.POST_RENDER_PROOF,
        "Encoded authored ROI is empty and requires renderer/geometry diagnosis",
    ),
    "TEXT_LAYOUT_REFERENCE_VIOLATION": _policy(
        "TEXT_LAYOUT_REFERENCE_VIOLATION",
        "composition",
        FailureDisposition.RECOVER,
        "Text may use bounded reflow/scale and optional-cue degradation after primary placement",
    ),
    "VISUAL_WHITE_FLASH": _policy(
        "VISUAL_WHITE_FLASH",
        "render",
        FailureDisposition.RECOVER,
        "A bounded strict-handoff rerender can repair an encoded blank boundary",
    ),
    "AUDIO_VIDEO_DRIFT": _policy(
        "AUDIO_VIDEO_DRIFT",
        "final",
        FailureDisposition.RECOVER,
        "Final mux can be rebuilt without changing semantic authority",
    ),
    "FINAL_MISSING_AUDIO": _policy(
        "FINAL_MISSING_AUDIO",
        "final",
        FailureDisposition.RECOVER,
        "Final mux can restore the authored narration stream",
    ),
    "FINAL_MISSING_OUTPUT": _policy(
        "FINAL_MISSING_OUTPUT",
        "render",
        FailureDisposition.RECOVER,
        "Verified plan may be rendered again when the output file is absent",
    ),
    "FINAL_UNREADABLE_MEDIA": _policy(
        "FINAL_UNREADABLE_MEDIA",
        "render",
        FailureDisposition.RECOVER,
        "Verified plan may be rendered again when output media is structurally unreadable",
    ),
    "FINAL_MISSING_VIDEO": _policy(
        "FINAL_MISSING_VIDEO",
        "render",
        FailureDisposition.RECOVER,
        "Verified plan may be rendered again when the video stream is missing",
    ),
}


def failure_policy(code: str) -> FailurePolicy | None:
    return HISTORICAL_FAILURE_POLICIES.get(str(code).strip())
