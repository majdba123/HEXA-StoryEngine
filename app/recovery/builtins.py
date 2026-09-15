from app.recovery.models import KnownIssue, RecoveryStatus


BUILTIN_ISSUES = [
    KnownIssue(code="ASSET_BAD_CUTOUT", description="Asset extraction is visibly invalid", affected_stage="cutout", handler="retry_cutout", status=RecoveryStatus.proven),
    KnownIssue(code="ASSET_WHITE_HALO", description="White/opaque halo around extracted asset", affected_stage="cutout", handler="retry_cutout", status=RecoveryStatus.proven),
    KnownIssue(code="ELEMENT_APPEARS_TOO_EARLY", description="Visual element appears before its narration cue", affected_stage="story", handler="rebuild_story_timing", status=RecoveryStatus.proven),
    KnownIssue(code="LOW_SCREEN_OCCUPANCY", description="Composition leaves excessive unused frame area", affected_stage="composition", handler="rebuild_composition", status=RecoveryStatus.proven),
    KnownIssue(code="MULTI_ELEMENT_POP", description="Too many elements enter at the same time", affected_stage="motion", handler="rebuild_motion", status=RecoveryStatus.proven),
    KnownIssue(code="AUDIO_VIDEO_DRIFT", description="Final audio/video timing drifts", affected_stage="final", handler="remux_audio", status=RecoveryStatus.proven),
]
