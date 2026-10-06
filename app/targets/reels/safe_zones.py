from __future__ import annotations

from app.targets.models import FrameMargins, NormalizedRect, TargetSafeZones

# The single Reels safe-zone policy (1080x1920). Short-form players overlay their own UI
# on the video: a header strip at the top, caption/account/audio rows at the bottom and an
# action rail (like/comment/share) on the right. Those regions are reserved: no important
# artwork or text may enter them. Values are conservative across the common players and
# live here only, never in Story, Choreography, Motion or the renderer.
REELS_TOP_UI = NormalizedRect(left=0.0, top=0.0, right=1.0, bottom=0.07)
REELS_BOTTOM_UI = NormalizedRect(left=0.0, top=0.80, right=1.0, bottom=1.0)
REELS_ACTION_RAIL = NormalizedRect(left=0.92, top=0.52, right=1.0, bottom=0.80)

REELS_SAFE_ZONES = TargetSafeZones(
    # Important artwork: centred column clear of the rail, header and caption rows.
    content=NormalizedRect(left=0.08, top=0.12, right=0.92, bottom=0.78),
    # Important text: clear of all reserved UI (asymmetric to avoid the action rail).
    text_margins=FrameMargins(left=0.07, top=0.075, right=0.10, bottom=0.21),
    reserved=(REELS_TOP_UI, REELS_BOTTOM_UI, REELS_ACTION_RAIL),
    min_edge_padding_px=48,
)

# Portrait reading lane: responsive layout keeps the upper band of the content frame
# free so narration text has a dedicated home above the artwork, as in short-form edits.
# Inset from the content frame by the minimum edge padding so no artwork can touch the
# action rail or the caption rows even after rounding.
REELS_ART_REGION = NormalizedRect(left=0.09, top=0.19, right=0.91, bottom=0.77)
