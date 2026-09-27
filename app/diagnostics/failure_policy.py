from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class FailureDisposition(StrEnum):
    PREVENT = "prevent"
    FAIL_FAST = "fail_fast"
    POST_RENDER_PROOF = "post_render_proof"


@dataclass(frozen=True, slots=True)
class FailurePolicy:
    code: str
    owner_stage: str
    disposition: FailureDisposition
    reason: str


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


FAILURE_POLICIES: dict[str, FailurePolicy] = {
    "HEXA_ERROR": _policy(
        "HEXA_ERROR", "pipeline", FailureDisposition.FAIL_FAST,
        "Generic HEXA failure is terminal and requires diagnosis",
    ),
    "DEPENDENCY_UNAVAILABLE": _policy(
        "DEPENDENCY_UNAVAILABLE", "input", FailureDisposition.FAIL_FAST,
        "A required runtime dependency is unavailable",
    ),
    "STAGE_FAILED": _policy(
        "STAGE_FAILED", "pipeline", FailureDisposition.FAIL_FAST,
        "Unclassified stage failure must be diagnosed at its owner",
    ),
    "GENERATION_CANCELLED": _policy(
        "GENERATION_CANCELLED", "pipeline", FailureDisposition.FAIL_FAST,
        "Explicit cancellation is terminal control flow and must not be intercepted",
    ),
    "AUDIO_INPUT_MISSING": _policy(
        "AUDIO_INPUT_MISSING", "input", FailureDisposition.FAIL_FAST,
        "Narration media is required before production planning starts",
    ),
    "FFPROBE_UNAVAILABLE": _policy(
        "FFPROBE_UNAVAILABLE", "input", FailureDisposition.FAIL_FAST,
        "Media probing is a required production dependency",
    ),
    "MEDIA_PROBE_FAILED": _policy(
        "MEDIA_PROBE_FAILED", "input", FailureDisposition.FAIL_FAST,
        "Narration/media cannot be trusted when ffprobe fails",
    ),
    "MEDIA_PROBE_INVALID_METADATA": _policy(
        "MEDIA_PROBE_INVALID_METADATA", "input", FailureDisposition.FAIL_FAST,
        "Invalid media metadata must be rejected before expensive work",
    ),
    "MEDIA_DURATION_INVALID": _policy(
        "MEDIA_DURATION_INVALID", "input", FailureDisposition.FAIL_FAST,
        "Non-positive or invalid media duration cannot establish timing authority",
    ),
    "WORKSPACE_NOT_WRITABLE": _policy(
        "WORKSPACE_NOT_WRITABLE", "input", FailureDisposition.FAIL_FAST,
        "Workspace storage must be writable before generation starts",
    ),
    "OUTPUT_ROOT_NOT_WRITABLE": _policy(
        "OUTPUT_ROOT_NOT_WRITABLE", "input", FailureDisposition.FAIL_FAST,
        "Output storage must be writable before generation starts",
    ),
    "CUTOUT_BACKEND_REQUIRED": _policy(
        "CUTOUT_BACKEND_REQUIRED", "cutout", FailureDisposition.FAIL_FAST,
        "Required production extraction backend is unavailable",
    ),
    "SEMANTIC_RUNTIME_UNAVAILABLE": _policy(
        "SEMANTIC_RUNTIME_UNAVAILABLE", "story", FailureDisposition.FAIL_FAST,
        "Required semantic runtime is unavailable and meaning must not be guessed",
    ),
    "ALIGNMENT_PREFLIGHT_UNAVAILABLE": _policy(
        "ALIGNMENT_PREFLIGHT_UNAVAILABLE", "input", FailureDisposition.FAIL_FAST,
        "Production forced-alignment preflight is unavailable",
    ),
    "ALIGNMENT_RUNTIME_UNAVAILABLE": _policy(
        "ALIGNMENT_RUNTIME_UNAVAILABLE", "input", FailureDisposition.FAIL_FAST,
        "Forced-alignment runtime is unavailable",
    ),
    "ALIGNMENT_MODEL_NOT_CONFIGURED": _policy(
        "ALIGNMENT_MODEL_NOT_CONFIGURED", "input", FailureDisposition.FAIL_FAST,
        "Required alignment language model is not configured",
    ),
    "ALIGNMENT_MODEL_LOAD_FAILED": _policy(
        "ALIGNMENT_MODEL_LOAD_FAILED", "input", FailureDisposition.FAIL_FAST,
        "Required alignment model could not be loaded",
    ),
    "ALIGNMENT_SCRIPT_UNSUPPORTED": _policy(
        "ALIGNMENT_SCRIPT_UNSUPPORTED", "input", FailureDisposition.FAIL_FAST,
        "Narration script cannot be aligned safely by the configured production path",
    ),
    "FFMPEG_CAPABILITY_PROBE_FAILED": _policy(
        "FFMPEG_CAPABILITY_PROBE_FAILED", "input", FailureDisposition.FAIL_FAST,
        "FFmpeg capabilities could not be established safely",
    ),
    "RENDER_PREFLIGHT_EMPTY": _policy(
        "RENDER_PREFLIGHT_EMPTY", "input", FailureDisposition.FAIL_FAST,
        "Production render preflight produced no valid encoded output",
    ),
    "FINAL_MUX_PREFLIGHT_FAILED": _policy(
        "FINAL_MUX_PREFLIGHT_FAILED", "input", FailureDisposition.FAIL_FAST,
        "Production mux path failed during preflight",
    ),
    "FINAL_MUX_PREFLIGHT_EMPTY": _policy(
        "FINAL_MUX_PREFLIGHT_EMPTY", "input", FailureDisposition.FAIL_FAST,
        "Production mux preflight produced no output",
    ),
    "FINAL_MUX_FAILED": _policy(
        "FINAL_MUX_FAILED", "final", FailureDisposition.FAIL_FAST,
        "Final mux failure is terminal and remains owned by Final",
    ),
    "FFMPEG_COMMAND_FAILED": _policy(
        "FFMPEG_COMMAND_FAILED", "render", FailureDisposition.FAIL_FAST,
        "Unclassified FFmpeg command failure requires stderr diagnosis",
    ),
    "RENDER_PROCESS_OS_ERROR": _policy(
        "RENDER_PROCESS_OS_ERROR", "render", FailureDisposition.FAIL_FAST,
        "Operating-system render process failure is terminal and remains owned by Render",
    ),
    "RENDER_PROCESS_COMMAND_LIMIT": _policy(
        "RENDER_PROCESS_COMMAND_LIMIT", "render", FailureDisposition.PREVENT,
        "Renderer must keep production filter graphs out of process command-length limits",
    ),
    "STORY_SYNC_INVALID": _policy(
        "STORY_SYNC_INVALID", "story", FailureDisposition.PREVENT,
        "Story must respect narration timing authority before downstream planning",
    ),
    "COMPETING_ENTRY_FOCUS": _policy(
        "COMPETING_ENTRY_FOCUS", "choreography", FailureDisposition.PREVENT,
        "Focus allocation must prevent simultaneous competing hero entries",
    ),
    "DUPLICATE_SEMANTIC_ENTRY_ACCENT": _policy(
        "DUPLICATE_SEMANTIC_ENTRY_ACCENT", "choreography", FailureDisposition.PREVENT,
        "A semantic event must not receive duplicate entry accents",
    ),
    "INCONSISTENT_BEAT_PACE": _policy(
        "INCONSISTENT_BEAT_PACE", "choreography", FailureDisposition.PREVENT,
        "Reference rhythm planning must avoid inconsistent local beat pace",
    ),
    "PACE_WHIPLASH": _policy(
        "PACE_WHIPLASH", "choreography", FailureDisposition.PREVENT,
        "Reference rhythm planning must prevent abrupt unsupported pace changes",
    ),
    "LAYOUT_REFERENCE_VIOLATION": _policy(
        "LAYOUT_REFERENCE_VIOLATION", "composition", FailureDisposition.PREVENT,
        "Composition must satisfy the shared reference layout contract before render",
    ),
    "TEXT_LAYER_MISSING": _policy(
        "TEXT_LAYER_MISSING", "text", FailureDisposition.PREVENT,
        "Required text cues must be authored before pre-render QA",
    ),
    "MOTION_REFERENCE_VIOLATION": _policy(
        "MOTION_REFERENCE_VIOLATION", "motion", FailureDisposition.PREVENT,
        "Motion must remain within the approved Reference Gesture Language",
    ),
    "MOTION_INFEASIBLE_BEFORE_RENDER": _policy(
        "MOTION_INFEASIBLE_BEFORE_RENDER", "motion", FailureDisposition.PREVENT,
        "Planner must fail closed when readability and comfort cannot both be satisfied",
    ),
    "MOTION_READABILITY_CONTRACT_BROKEN": _policy(
        "MOTION_READABILITY_CONTRACT_BROKEN", "motion", FailureDisposition.PREVENT,
        "Planner/QA readability contract divergence is an internal invariant failure",
    ),
    "SEGMENT_PROGRAM_MISSING": _policy(
        "SEGMENT_PROGRAM_MISSING", "motion", FailureDisposition.PREVENT,
        "Every semantic motion segment must have an executable reference program",
    ),
    "EXIT_NOT_READABLE": _policy(
        "EXIT_NOT_READABLE", "motion", FailureDisposition.PREVENT,
        "Authored exit motion must remain perceptually readable",
    ),
    "SEGMENT_GEOMETRY_DRIFT": _policy(
        "SEGMENT_GEOMETRY_DRIFT", "motion", FailureDisposition.PREVENT,
        "Motion must settle exactly on Composition-owned geometry",
    ),
    "NO_RELATION_OVERLAP": _policy(
        "NO_RELATION_OVERLAP", "motion", FailureDisposition.PREVENT,
        "Relation source/target phases must overlap when the authored relation requires it",
    ),
    "PAYOFF_PRECEDES_CAUSE": _policy(
        "PAYOFF_PRECEDES_CAUSE", "motion", FailureDisposition.PREVENT,
        "Result payoff cannot precede its authored cause/reaction sentence",
    ),
    "MISSING_SCENE_BRIDGE": _policy(
        "MISSING_SCENE_BRIDGE", "continuity", FailureDisposition.PREVENT,
        "Every scene boundary requiring continuity must have an authored legal bridge",
    ),
    "EMPTY_SCENE_BRIDGE": _policy(
        "EMPTY_SCENE_BRIDGE", "continuity", FailureDisposition.PREVENT,
        "Continuity bridge must have a valid outgoing/incoming carrier",
    ),
    "SCENE_BRIDGE_TOO_SHORT": _policy(
        "SCENE_BRIDGE_TOO_SHORT", "continuity", FailureDisposition.PREVENT,
        "Continuity bridge must meet the shared minimum readable duration",
    ),
    "SCENE_BRIDGE_OVERRUN": _policy(
        "SCENE_BRIDGE_OVERRUN", "continuity", FailureDisposition.PREVENT,
        "Continuity bridge cannot run beyond its Story-owned boundary",
    ),
    "INCOMING_BEFORE_STORY": _policy(
        "INCOMING_BEFORE_STORY", "continuity", FailureDisposition.PREVENT,
        "Incoming scene assets cannot appear before Story timing authority",
    ),
    "BLUR_NOT_EXPLICITLY_AUTHORED": _policy(
        "BLUR_NOT_EXPLICITLY_AUTHORED", "continuity", FailureDisposition.PREVENT,
        "Blur transitions are legal only when explicitly authored",
    ),
    "BLUR_BRIDGE_WITHOUT_BLUR": _policy(
        "BLUR_BRIDGE_WITHOUT_BLUR", "continuity", FailureDisposition.PREVENT,
        "Authored blur bridge must execute its declared visual treatment",
    ),
    "UNAUTHORED_BLUR": _policy(
        "UNAUTHORED_BLUR", "continuity", FailureDisposition.PREVENT,
        "Renderer must not invent blur continuity",
    ),
    "ASSET_BAD_CUTOUT": _policy(
        "ASSET_BAD_CUTOUT",
        "cutout",
        FailureDisposition.PREVENT,
        "Extraction must reject invalid cutouts while preserving Final Package semantics",
    ),
    "ASSET_WHITE_HALO": _policy(
        "ASSET_WHITE_HALO",
        "cutout",
        FailureDisposition.PREVENT,
        "Extraction safety must reject halo/ghost defects before assets leave Pass2",
    ),
    "ELEMENT_APPEARS_TOO_EARLY": _policy(
        "ELEMENT_APPEARS_TOO_EARLY",
        "story",
        FailureDisposition.PREVENT,
        "Story owns reveal timing and must emit narration-bounded timing",
    ),
    "ELEMENT_APPEARS_TOO_LATE": _policy(
        "ELEMENT_APPEARS_TOO_LATE",
        "motion",
        FailureDisposition.PREVENT,
        "Motion must fit execution inside the Story-owned activation window",
    ),
    "BAD_HANDOFF": _policy(
        "BAD_HANDOFF",
        "story",
        FailureDisposition.PREVENT,
        "Story must produce a valid attention handoff without changing semantic authority",
    ),
    "LOW_SCREEN_OCCUPANCY": _policy(
        "LOW_SCREEN_OCCUPANCY",
        "composition",
        FailureDisposition.PREVENT,
        "Composition must produce a legal layout while preserving semantic authority",
    ),
    "MULTI_ELEMENT_POP": _policy(
        "MULTI_ELEMENT_POP",
        "motion",
        FailureDisposition.PREVENT,
        "Motion must produce reveal spacing that preserves semantic order",
    ),
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
    "RHYTHM_CONTRACT_VIOLATIONS": _policy(
        "RHYTHM_CONTRACT_VIOLATIONS",
        "choreography",
        FailureDisposition.PREVENT,
        "Choreography rhythm aggregates contain one or more construction-time contract violations",
    ),
    "MOTION_CONTRACT_VIOLATIONS": _policy(
        "MOTION_CONTRACT_VIOLATIONS",
        "motion",
        FailureDisposition.PREVENT,
        "Motion aggregate contains one or more authored semantic contract violations",
    ),
    "CONTINUITY_CONTRACT_VIOLATIONS": _policy(
        "CONTINUITY_CONTRACT_VIOLATIONS",
        "continuity",
        FailureDisposition.PREVENT,
        "Continuity aggregate contains one or more lifecycle/bridge contract violations",
    ),
    "RENDERED_MOTION_CONTRACT_VIOLATIONS": _policy(
        "RENDERED_MOTION_CONTRACT_VIOLATIONS",
        "render",
        FailureDisposition.POST_RENDER_PROOF,
        "Encoded motion aggregate contains one or more post-render proof violations",
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
        FailureDisposition.POST_RENDER_PROOF,
        "Encoded motion below the perceptual floor is post-render evidence of a Motion/Render contract failure",
    ),
    "TERMINAL_EXIT_ON_PERSISTENT_ASSET": _policy(
        "TERMINAL_EXIT_ON_PERSISTENT_ASSET",
        "motion",
        FailureDisposition.PREVENT,
        "Persistent asset lifecycle cannot contain a terminal leave before continuation",
    ),
    "PREMATURE_SEMANTIC_EXIT": _policy(
        "PREMATURE_SEMANTIC_EXIT",
        "motion",
        FailureDisposition.PREVENT,
        "Terminal release cannot precede proven future semantic use of the exact asset",
    ),
    "SEMANTIC_LIFETIME_VIOLATIONS": _policy(
        "SEMANTIC_LIFETIME_VIOLATIONS",
        "motion",
        FailureDisposition.PREVENT,
        "Semantic lifetime aggregate contains one or more premature terminal releases",
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
        "Missing encoded evidence frames are a post-render proof failure requiring owner diagnosis",
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
        FailureDisposition.PREVENT,
        "Text may use bounded reflow/scale and optional-cue degradation after primary placement",
    ),
    "VISUAL_WHITE_FLASH": _policy(
        "VISUAL_WHITE_FLASH",
        "render",
        FailureDisposition.POST_RENDER_PROOF,
        "Encoded blank handoff frames are post-render proof failures owned by Renderer/Continuity",
    ),
    "AUDIO_VIDEO_DRIFT": _policy(
        "AUDIO_VIDEO_DRIFT",
        "final",
        FailureDisposition.POST_RENDER_PROOF,
        "A/V timing mismatch is a post-render proof failure owned by Final muxing",
    ),
    "FINAL_MISSING_AUDIO": _policy(
        "FINAL_MISSING_AUDIO",
        "final",
        FailureDisposition.POST_RENDER_PROOF,
        "Missing narration audio is a post-render proof failure owned by Final muxing",
    ),
    "FINAL_MISSING_OUTPUT": _policy(
        "FINAL_MISSING_OUTPUT",
        "render",
        FailureDisposition.POST_RENDER_PROOF,
        "Missing output is a post-render proof failure owned by Render",
    ),
    "FINAL_UNREADABLE_MEDIA": _policy(
        "FINAL_UNREADABLE_MEDIA",
        "render",
        FailureDisposition.POST_RENDER_PROOF,
        "Structurally unreadable output is a post-render proof failure owned by Render",
    ),
    "FINAL_MISSING_VIDEO": _policy(
        "FINAL_MISSING_VIDEO",
        "render",
        FailureDisposition.POST_RENDER_PROOF,
        "Missing video stream is a post-render proof failure owned by Render",
    ),
}


def failure_policy(code: str) -> FailurePolicy | None:
    return FAILURE_POLICIES.get(str(code).strip())
