from app.recovery.models import KnownIssue, RecoveryStatus


BUILTIN_ISSUES = [
    KnownIssue(code="ASSET_BAD_CUTOUT", description="Asset extraction is visibly invalid", affected_stage="cutout", handler="retry_cutout", status=RecoveryStatus.proven),
    KnownIssue(
        code="ASSET_WHITE_HALO",
        description="White/opaque halo around extracted asset",
        affected_stage="cutout",
        handler="retry_cutout",
        status=RecoveryStatus.candidate,
        handler_version=2,
    ),
    KnownIssue(code="ELEMENT_APPEARS_TOO_EARLY", description="Visual element appears before its narration cue", affected_stage="story", handler="rebuild_story_timing", status=RecoveryStatus.proven),
    KnownIssue(code="ELEMENT_APPEARS_TOO_LATE", description="Visual element appears too late for its narration cue", affected_stage="motion", handler="rebuild_motion", status=RecoveryStatus.proven),
    KnownIssue(code="BAD_HANDOFF", description="Visual attention handoff is missing or invalid", affected_stage="story", handler="rebuild_story_timing", status=RecoveryStatus.proven),
    KnownIssue(code="LOW_SCREEN_OCCUPANCY", description="Composition leaves excessive unused frame area", affected_stage="composition", handler="rebuild_composition", status=RecoveryStatus.proven),
    KnownIssue(code="MULTI_ELEMENT_POP", description="Too many elements enter at the same time", affected_stage="motion", handler="rebuild_motion", status=RecoveryStatus.proven),
    KnownIssue(code="TEXT_LAYOUT_REFERENCE_VIOLATION", description="Text cannot fit safely around visuals at its rendered time", affected_stage="composition", handler="repair_text_layout", status=RecoveryStatus.proven, max_attempts=3),
    KnownIssue(code="AUDIO_VIDEO_DRIFT", description="Final audio/video timing drifts", affected_stage="final", handler="remux_audio", status=RecoveryStatus.proven),
    KnownIssue(code="FINAL_MISSING_AUDIO", description="Final media has no audio stream", affected_stage="final", handler="remux_audio", status=RecoveryStatus.proven),
    KnownIssue(code="FINAL_MISSING_OUTPUT", description="Final output file is missing", affected_stage="render", handler="rerender", status=RecoveryStatus.proven),
    KnownIssue(code="FINAL_UNREADABLE_MEDIA", description="Final media cannot be probed", affected_stage="render", handler="rerender", status=RecoveryStatus.proven),
    KnownIssue(code="FINAL_MISSING_VIDEO", description="Final media has no video stream", affected_stage="render", handler="rerender", status=RecoveryStatus.proven),
    KnownIssue(code="VISUAL_WHITE_FLASH", description="Final video contains a true blank internal handoff frame", affected_stage="render", handler="rerender_strict_handoff", status=RecoveryStatus.proven, max_attempts=1),
]
