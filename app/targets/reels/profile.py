from __future__ import annotations

from app.targets.models import VisualTargetProfile
from app.targets.reels.safe_zones import REELS_SAFE_ZONES

REELS_9_16 = VisualTargetProfile(
    target_id="REELS_9_16",
    width=1080,
    height=1920,
    fps=30,
    safe_zones=REELS_SAFE_ZONES,
    layout_policy="responsive_portrait",
    output_suffix="REELS",
    description="Portrait 9:16; responsive reflow of the same authored scene.",
    layout_options={
        # Families whose visible footprints overlap are in authored contact (a hand on
        # the object it holds): one rigid block. Merely neighbouring families may reflow.
        "contact_px": 0.0,
        # Visible spacing between unrelated / related blocks (target px). The related gap
        # leaves room for a readable authored connector (2 x 14 px clearance + 70 px).
        "gap_px": 64.0,
        "related_gap_px": 120.0,
        # Never enlarge artwork beyond its certified 16:9 pixel size.
        "max_scale": 1.0,
    },
)
