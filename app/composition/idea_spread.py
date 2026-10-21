"""Idea spread: two pictures of one idea share the screen (pacing review 2026-10-21).

Measured on the 4 cached Final Packages (montage 826e2597): a picture is complete for a
median 0.6 s and 80-87 % of pictures are complete for under 1 s, because every package
scene (one per ~2.3 s) fills the whole frame and its last element lands on the sentence's
last word. The idea board already keeps old elements until a new one lands on their spot,
but every scene reuses the same spots, so the old picture is gone within a few frames.
The references build one idea on one picture for 3-7 s (docs/reference-motion-grammar.md
section 6) and move a held element aside to make room for the next one (G3, G4).

When the next scene continues the same idea (the idea-board rule, ``idea_links``), the
current picture glides as one rigid block into the right half of the frame at the next
scene's first frame and stays complete there; the next scene is built in the left half
(Arabic reads right to left: the earlier picture sits on the right). Along a longer chain
the halves alternate: the third picture takes the right half the first one has just left.
The first picture of a chain keeps its full-frame layout until the glide; every later one
is laid out in its half (a rigid, uniform scale of the staged scene: relations, order,
z and aspect are unchanged). Timing never changes: nothing appears earlier or later.

Owner split: Composition decides the chains and the half layouts (``CompositionBeat.
idea_spread``); Boundary holds the old picture and plans its glide on the idea board;
Text keeps keywords off the held picture (``held_items``); the renderer executes the glide.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.layout.footprint import AlphaFootprintResolver
from app.models import LayoutItem, StoryBeat, VisualAsset
from app.shared.narration import idea_links
from app.targets import VisualTargetProfile, active_target

Box = tuple[float, float, float, float]

IDEA_SPREAD = True
SPREAD_PLACEMENT_SOURCE = "authored_idea_spread"
FIRST_SLOT = "right"           # Arabic reading order: the earlier picture on the right
SPREAD_GAP = 0.04              # frame-width share kept free between the two halves
SPREAD_MIN_SCALE = 0.4         # a picture that only fits smaller stays full frame
GLIDE_FRAMES = 10              # reference G3: a held element relocates in ~11 frames


@dataclass
class SpreadResult:
    items: dict[str, list[LayoutItem]]                         # scene id -> layout
    info: dict[str, dict] = field(default_factory=dict)        # scene id -> CompositionBeat.idea_spread
    held_items: dict[str, list[LayoutItem]] = field(default_factory=dict)  # beat id -> held picture
    evidence: dict[str, str] = field(default_factory=dict)     # scene id -> decision


def enabled() -> bool:
    """The spread lives on the idea board: it is off whenever the board is."""
    from app.boundary import release  # lazy: Boundary imports Composition

    return IDEA_SPREAD and release.IDEA_BOARD and release.SCENE_WHIP


def links(beats: list[StoryBeat]) -> set[str]:
    from app.boundary import release

    return idea_links(beats, min_seconds=release.IDEA_MIN_SECONDS if release.IDEA_CLOCK else 0.0)


class IdeaSpreadPlanner:
    def __init__(self, *, footprints: AlphaFootprintResolver | None = None) -> None:
        self.footprints = footprints or AlphaFootprintResolver()

    def plan(
        self,
        beats: list[StoryBeat],
        staged: dict[str, list[LayoutItem]],
        assets: list[VisualAsset],
        target: VisualTargetProfile | None = None,
    ) -> SpreadResult:
        result = SpreadResult(items=dict(staged))
        if not enabled() or not beats:
            return result
        by_id = {asset.id: asset for asset in assets}
        safe = (target or active_target()).safe_zones.content
        middle = (safe.left + safe.right) / 2
        slots = {"right": (middle + SPREAD_GAP / 2, safe.top, safe.right, safe.bottom),
                 "left": (safe.left, safe.top, middle - SPREAD_GAP / 2, safe.bottom)}
        other = {"right": "left", "left": "right"}
        joined = links(beats)
        scenes = list(dict.fromkeys(beat.scene_id for beat in beats))
        first_beat = {}
        for beat in beats:
            first_beat.setdefault(beat.scene_id, beat)

        # Rigid fit of each scene into each half; None when it would be too small to read.
        def fit(scene_id: str, slot: str) -> tuple[float, float, float, float, float] | None:
            items = staged.get(scene_id) or []
            if not items or any(not item.placement_source.startswith("authored") for item in items):
                return None
            boxes = [self.footprints.resolve(item, by_id.get(item.asset_id)).box for item in items]
            x0, y0 = min(b[0] for b in boxes), min(b[1] for b in boxes)
            x1, y1 = max(b[2] for b in boxes), max(b[3] for b in boxes)
            sx0, sy0, sx1, sy1 = slots[slot]
            scale = min(1.0, (sx1 - sx0) / max(1e-6, x1 - x0), (sy1 - sy0) / max(1e-6, y1 - y0))
            if scale < SPREAD_MIN_SCALE:
                return None
            return scale, (x0 + x1) / 2, (y0 + y1) / 2, (sx0 + sx1) / 2, (sy0 + sy1) / 2

        def place(items: list[LayoutItem], transform) -> list[LayoutItem]:
            scale, px, py, tx, ty = transform
            return [item.model_copy(update={
                "x": tx + (item.x - px) * scale, "y": ty + (item.y - py) * scale,
                "width": item.width * scale, "height": item.height * scale,
                "placement_source": SPREAD_PLACEMENT_SOURCE,
            }) for item in items]

        # previous: (scene id, slot it occupies or None when still full frame)
        previous: tuple[str, str | None] | None = None
        for scene_id in scenes:
            beat = first_beat[scene_id]
            if previous is not None and beat.id in joined:
                held_id, held_slot = previous
                held_slot = held_slot or FIRST_SLOT
                slot = other[held_slot]
                hold = fit(held_id, held_slot) if previous[1] is None else (1.0, 0.0, 0.0, 0.0, 0.0)
                own = fit(scene_id, slot)
                if hold is not None and own is not None:
                    if previous[1] is None:  # the chain starts: the held picture glides
                        scale, px, py, tx, ty = hold
                        result.info[held_id] = {**result.info.get(held_id, {}), "slot": held_slot,
                                                "hold_scale": round(scale, 6), "hold_pivot_x": px,
                                                "hold_pivot_y": py, "hold_to_x": tx, "hold_to_y": ty}
                        held_layout = place(result.items[held_id], hold)
                        result.evidence[held_id] = f"idea_spread:glides:{held_slot}:scale={scale:.2f}"
                    else:
                        result.info[held_id] = {**result.info[held_id], "hold_scale": 1.0}
                        held_layout = result.items[held_id]
                    result.items[scene_id] = place(result.items[scene_id], own)
                    result.info[scene_id] = {"slot": slot, "scale": round(own[0], 6), "joins": held_id}
                    result.held_items[beat.id] = held_layout
                    result.evidence[scene_id] = f"idea_spread:joins:{slot}:scale={own[0]:.2f}"
                    previous = (scene_id, slot)
                    continue
                result.evidence[scene_id] = "idea_spread:abstained:no_room"
            previous = (scene_id, None)
        return result
