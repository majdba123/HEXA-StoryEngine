"""Select a safe cardinal attention handoff, without inferring object identity.

The motion owners decide whether the proposed offset is feasible. Story, semantic
timing, Composition and Final Package data are never changed by this module.
"""
from __future__ import annotations

from app.models import CompositionBeat, LayoutItem, StoryBeat
from app.targets.context import active_target


def focus_handoff_direction(
    previous: StoryBeat | None,
    current: StoryBeat,
    layouts: dict[str, CompositionBeat],
    *,
    frame_width: int | None = None,
    frame_height: int | None = None,
) -> tuple[float, float] | None:
    """Return an incoming *start offset* in LEFT/RIGHT/TOP/BOTTOM direction.

    The first primary enters slightly from the previous focus location, then
    settles at its unchanged authored pose. Do not assume shared asset identity.
    """
    if previous is None or previous.scene_id == current.scene_id:
        return None
    if len(previous.primary_asset_ids) != 1 or len(current.primary_asset_ids) != 1:
        return None
    target = active_target()
    frame_width = frame_width if frame_width is not None else target.width
    frame_height = frame_height if frame_height is not None else target.height
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


def spatial_entry_direction(item: LayoutItem, *, frame_width: int | None = None,
                            frame_height: int | None = None) -> tuple[float, float]:
    """Choose a staging edge using physical pixel distance, never asset names.

    Spatially distributed art naturally enters from left, right, top and bottom.
    This only guides the entry gesture; collision/readability remains Motion-owned.
    """
    target = active_target()
    width = frame_width if frame_width is not None else target.width
    height = frame_height if frame_height is not None else target.height
    options = (
        (max(0.0, item.x - item.width / 2) * width, (-1.0, 0.0)),
        (max(0.0, 1 - item.x - item.width / 2) * width, (1.0, 0.0)),
        # A lateral entrance reads as travel across the frame; a vertical one only wins
        # when its edge is clearly closer (encoded review 2026-10-19: strict nearest-edge
        # sent near-corner art up from the bottom, 36 of 59 directional entries).
        (max(0.0, item.y - item.height / 2) * height * LATERAL_PREFERENCE, (0.0, -1.0)),
        (max(0.0, 1 - item.y - item.height / 2) * height * LATERAL_PREFERENCE, (0.0, 1.0)),
    )
    return min(options, key=lambda option: option[0])[1]


LATERAL_PREFERENCE = 1.6
