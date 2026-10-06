"""Output-format targets of the single shared visual engine.

A target owns frame facts (size, fps, safe zones) and its spatial projection policy.
Story, Choreography, Motion grammar, Text selection and the renderer stay shared.
"""

from app.targets.context import active_target, frame_size, visual_target
from app.targets.models import NormalizedRect, TargetSafeZones, VisualTargetProfile
from app.targets.registry import (
    REFERENCE_TARGET,
    SUPPORTED_VISUAL_TARGETS,
    composition_policy,
    target_by_id,
)
from app.targets.reels.profile import REELS_9_16
from app.targets.youtube.profile import YOUTUBE_16_9

__all__ = [
    "NormalizedRect",
    "REELS_9_16",
    "REFERENCE_TARGET",
    "SUPPORTED_VISUAL_TARGETS",
    "TargetSafeZones",
    "VisualTargetProfile",
    "YOUTUBE_16_9",
    "active_target",
    "composition_policy",
    "frame_size",
    "target_by_id",
    "visual_target",
]
