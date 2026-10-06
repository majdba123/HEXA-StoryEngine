from __future__ import annotations

from app.targets.models import FrameMargins, NormalizedRect, TargetSafeZones

# The certified 16:9 limits, unchanged: artwork uses the HEXA reference safe frame
# (HexaVisualProfile) and text uses the TextPlacementDirector margins. YouTube has no
# platform UI that covers the frame during playback, so nothing is reserved.
YOUTUBE_SAFE_ZONES = TargetSafeZones(
    content=NormalizedRect(left=0.04, top=0.05, right=0.96, bottom=0.95),
    text_margins=FrameMargins(left=0.045, top=0.055, right=0.045, bottom=0.055),
    reserved=(),
    min_edge_padding_px=0,
)
