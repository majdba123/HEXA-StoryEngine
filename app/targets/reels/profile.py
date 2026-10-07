from __future__ import annotations

from app.targets.models import VisualTargetProfile
from app.targets.reels.safe_zones import REELS_SAFE_ZONES

REELS_9_16 = VisualTargetProfile(
    target_id="REELS_9_16",
    width=1080,
    height=1920,
    fps=30,
    safe_zones=REELS_SAFE_ZONES,
    layout_policy="reference_projection",
    output_suffix="REELS",
    description="Portrait 9:16; uniform projection of the YouTube visual plan.",
)
