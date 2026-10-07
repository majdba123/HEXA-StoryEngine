from __future__ import annotations

from app.targets.models import TargetCompositionPolicy, VisualTargetProfile
from app.targets.reels.profile import REELS_9_16
from app.targets.youtube.profile import YOUTUBE_16_9

# The permanent list of production output formats. Every target-sensitive visual test
# parameterizes over this tuple, so a change to Choreography, Composition, Motion, Text,
# Boundary or Render is exercised against every format automatically.
SUPPORTED_VISUAL_TARGETS: tuple[VisualTargetProfile, ...] = (YOUTUBE_16_9, REELS_9_16)
REFERENCE_TARGET = YOUTUBE_16_9

_BY_ID = {target.target_id: target for target in SUPPORTED_VISUAL_TARGETS}
if len(_BY_ID) != len(SUPPORTED_VISUAL_TARGETS):
    raise RuntimeError("visual target ids must be unique")


def target_by_id(target_id: str) -> VisualTargetProfile:
    try:
        return _BY_ID[target_id]
    except KeyError as exc:
        raise KeyError(f"unknown visual target: {target_id}") from exc


def composition_policy(target: VisualTargetProfile) -> TargetCompositionPolicy:
    """Legacy spatial authoring policy; projected targets use ReferencePlanProjector."""
    if target.layout_policy == "authored_reference":
        from app.targets.youtube.composition import YouTubeCompositionPolicy

        return YouTubeCompositionPolicy()
    if target.layout_policy == "responsive_portrait":
        from app.targets.reels.composition import ReelsCompositionPolicy
        from app.targets.reels.safe_zones import REELS_ART_REGION

        options = target.layout_options
        return ReelsCompositionPolicy(
            frame=target.frame,
            art_region=REELS_ART_REGION,
            contact_px=options["contact_px"],
            gap_px=options["gap_px"],
            related_gap_px=options["related_gap_px"],
            max_scale=options["max_scale"],
        )
    raise ValueError(f"unsupported layout policy: {target.layout_policy}")
