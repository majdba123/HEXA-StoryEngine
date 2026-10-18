"""Select a safe cardinal attention handoff, without inferring object identity.

The motion owners decide whether the proposed offset is feasible. Story, semantic
timing, Composition and Final Package data are never changed by this module.
"""
from __future__ import annotations

from app.models import CompositionBeat, StoryBeat


def focus_handoff_direction(
    previous: StoryBeat | None,
    current: StoryBeat,
    layouts: dict[str, CompositionBeat],
    *,
    frame_width: int = 1920,
    frame_height: int = 1080,
) -> tuple[float, float] | None:
    """Return an incoming *start offset* in LEFT/RIGHT/TOP/BOTTOM direction.

    The first primary enters slightly from the previous focus location, then
    settles at its unchanged authored pose. Do not assume shared asset identity.
    """
    if previous is None or previous.scene_id == current.scene_id:
        return None
    if len(previous.primary_asset_ids) != 1 or len(current.primary_asset_ids) != 1:
        return None
    old_layout, new_layout = layouts.get(previous.id), layouts.get(current.id)
    if old_layout is None or new_layout is None:
        return None
    old = next((row for row in old_layout.items
                if row.asset_id == previous.primary_asset_ids[0]), None)
    new = next((row for row in new_layout.items
                if row.asset_id == current.primary_asset_ids[0]), None)
    if old is None or new is None:
        return None
    dx = (float(old.x) - float(new.x)) * frame_width
    dy = (float(old.y) - float(new.y)) * frame_height
    if max(abs(dx), abs(dy)) < 0.08 * min(frame_width, frame_height):
        return None
    if abs(dx) >= abs(dy):
        return (1.0 if dx > 0 else -1.0, 0.0)
    return (0.0, 1.0 if dy > 0 else -1.0)
