from __future__ import annotations

from app.targets.models import VisualTargetProfile
from app.targets.youtube.safe_zones import YOUTUBE_SAFE_ZONES

YOUTUBE_16_9 = VisualTargetProfile(
    target_id="YOUTUBE_16_9",
    width=1920,
    height=1080,
    fps=30,
    safe_zones=YOUTUBE_SAFE_ZONES,
    layout_policy="authored_reference",
    output_suffix="YOUTUBE",
    description="Landscape 16:9; the certified authored-geometry reference target.",
)
