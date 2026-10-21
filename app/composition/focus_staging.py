"""Focus staging: one dominant object per picture (2026-10-21 reference measurement).

Measured on both approved references (5 fps, characters excluded): the largest object stands
at a median 51-53 % of the frame height and is the ONLY coloured object on screen in most
frames (dominance 100 %, satellites 0); extra symbols are small. HEXA pictures reconstruct
the Final Package scene, where 2-3 objects of similar size compete (dominance 68-72 %), so
the eye has no anchor.

Per scene (all its beats share one decision), after projection and Sprint 4.3 staging:

* the anchor keeps the package artist's hierarchy: the clearly largest object; only when
  objects of similar size compete (each >= CONTENDER_SHARE of the largest) does meaning
  break the tie - the object a spoken keyword names, then PRIMARY, RESULT, the director's
  focus, then size. A clearly larger object is never shrunk in favour of a smaller one;
* the anchor grows toward ANCHOR_TARGET_HEIGHT (never more than ANCHOR_MAX_GROWTH, never
  above ANCHOR_MAX_HEIGHT) and moves CENTRE_PULL of the way toward the frame centre;
* every other object shrinks to at most SATELLITE_RATIO of the anchor's longest side
  (never below SATELLITE_MIN_SIDE, never grows), keeps its side of the anchor and takes the
  closest free spot along that direction (the references cluster symbols beside the anchor).

Rigid units: a Pass2 family, and anything that touches another drawing in the authored
picture (a hand holding a card), moves and scales as one; a unit containing a character
never moves. Timing, z order and aspect never change. The scene is left exactly as
authored when it carries drawn arrow / path art, has no clear anchor, Sprint 4.3 already
staged it, or any unit has no room, leaves the safe frame or would swap its left/right or
above/below order with another object.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import atan2, cos, hypot, radians, sin

from app.assets import AssetManager
from app.composition.semantic_staging import STAGED_PLACEMENT_SOURCE
from app.layout.footprint import AlphaFootprintResolver
from app.models import LayoutItem, StoryBeat, VisualAsset
from app.render.write_on import _is_path
from app.targets import active_target

Box = tuple[float, float, float, float]

FOCUS_STAGING = True
FOCUS_PLACEMENT_SOURCE = "authored_focus_staging"
ANCHOR_TARGET_HEIGHT = 0.50
ANCHOR_MAX_HEIGHT = 0.62
ANCHOR_MAX_WIDTH = 0.55
ANCHOR_MAX_GROWTH = 1.6
CENTRE_PULL = 0.35
SATELLITE_RATIO = 0.6
SATELLITE_MIN_SIDE = 0.14     # longest side, in frame heights
CONTENDER_SHARE = 0.55
GAP = 0.02                 # clearance between staged footprints (frame units)
CONTACT = 0.008            # authored drawings this close form one rigid unit
MIN_CHANGE = 0.06          # smaller scale changes than this are not worth a redesign
ORDER_MARGIN = 0.04        # left/right or above/below separations that must not swap
_ANGLES = (0.0, 15.0, -15.0, 30.0, -30.0)
_RADIAL_STEPS = 80
_RADIAL_STEP = 0.011


@dataclass
class _Unit:
    members: list[LayoutItem]
    box: Box
    character: bool
    roles: set[str] = field(default_factory=set)

    @property
    def ids(self) -> set[str]:
        return {item.asset_id for item in self.members}

    @property
    def height(self) -> float:
        return self.box[3] - self.box[1]

    @property
    def width(self) -> float:
        return self.box[2] - self.box[0]

    @property
    def area(self) -> float:
        return self.width * self.height

    @property
    def centre(self) -> tuple[float, float]:
        return ((self.box[0] + self.box[2]) / 2, (self.box[1] + self.box[3]) / 2)


@dataclass(frozen=True, slots=True)
class FocusStagingResult:
    items: list[LayoutItem]
    evidence: str
    anchor_id: str | None = None
    anchor_scale: float = 1.0
    satellites: int = 0


class FocusStagingPlanner:
    def __init__(self, *, footprints: AlphaFootprintResolver | None = None) -> None:
        self.footprints = footprints or AlphaFootprintResolver()

    def stage(
        self,
        items: list[LayoutItem],
        assets: list[VisualAsset],
        beats: list[StoryBeat],
        focus_asset_id: str | None,
        spoken_asset_ids: set[str] | None = None,
    ) -> FocusStagingResult:
        anchor_id: str | None = None

        def abstain(reason: str) -> FocusStagingResult:
            return FocusStagingResult(items=items, evidence=f"focus_staging:abstained:{reason}",
                                      anchor_id=anchor_id)

        if not FOCUS_STAGING:  # switched off (safe level, strict tests): leave no trace
            return FocusStagingResult(items=items, evidence="", anchor_id=None)
        if any(not item.placement_source.startswith("authored") for item in items):
            return abstain("fallback_geometry")
        if any(item.placement_source == STAGED_PLACEMENT_SOURCE for item in items):
            return abstain("already_staged")  # Sprint 4.3 moved it for a relation: keep that
        by_id = {asset.id: asset for asset in assets}
        roles, path_art = self._roles(beats)
        if path_art:
            return abstain("authored_path_art")
        units = self._units(items, by_id, roles)
        objects = [unit for unit in units if not unit.character]
        if not objects:
            return abstain("no_objects")
        anchor = self._anchor(objects, focus_asset_id, spoken_asset_ids or set())
        anchor_id = self._primary_id(anchor)
        target = active_target()
        safe = target.safe_zones.content
        frame = (safe.left, safe.top, safe.right, safe.bottom)
        aspect = target.width / target.height

        def side(unit: _Unit, scale: float = 1.0) -> float:
            return max(unit.height, unit.width * aspect) * scale

        growth = min(ANCHOR_MAX_GROWTH, max(ANCHOR_TARGET_HEIGHT / anchor.height, 1.0),
                     ANCHOR_MAX_HEIGHT / anchor.height, ANCHOR_MAX_WIDTH / anchor.width)
        growth = max(1.0, growth)
        shrink = {
            id(unit): min(1.0, max(SATELLITE_MIN_SIDE, SATELLITE_RATIO * side(anchor, growth)) / side(unit))
            for unit in objects if unit is not anchor
        }
        if growth < 1.0 + MIN_CHANGE and all(value > 1.0 - MIN_CHANGE for value in shrink.values()):
            return abstain("already_dominant")

        fixed = [unit.box for unit in units if unit.character]
        placed: dict[int, tuple[float, Box]] = {}
        anchor_box = self._place_anchor(anchor, growth, frame, fixed)
        if anchor_box is None:
            return abstain("anchor_has_no_room")
        growth, anchor_box = anchor_box
        placed[id(anchor)] = (growth, anchor_box)
        obstacles = [*fixed, anchor_box]
        acx, acy = anchor.centre
        ncx, ncy = _centre(anchor_box)
        for unit in sorted((u for u in objects if u is not anchor),
                           key=lambda u: hypot(u.centre[0] - acx, u.centre[1] - acy)):
            scale = shrink[id(unit)]
            box = self._place_satellite(unit, scale, (acx, acy), (ncx, ncy), frame, obstacles)
            if box is None:
                return abstain("satellite_has_no_room")
            placed[id(unit)] = (scale, box)
            obstacles.append(box)
        moved = [unit for unit in objects if id(unit) in placed]
        if self._order_swapped(moved, placed):
            return abstain("order_would_swap")

        output: list[LayoutItem] = []
        for item in items:
            unit = next(unit for unit in units if item.asset_id in unit.ids)
            if id(unit) not in placed:
                output.append(item)
                continue
            scale, box = placed[id(unit)]
            (ox, oy), (nx, ny) = unit.centre, _centre(box)
            output.append(item.model_copy(update={
                "x": nx + (item.x - ox) * scale,
                "y": ny + (item.y - oy) * scale,
                "width": item.width * scale,
                "height": item.height * scale,
                "placement_source": FOCUS_PLACEMENT_SOURCE,
            }))
        return FocusStagingResult(
            items=output,
            evidence=f"focus_staging:applied:anchor={anchor_id}:scale={growth:.2f}:satellites={len(moved) - 1}",
            anchor_id=anchor_id,
            anchor_scale=round(growth, 3),
            satellites=len(moved) - 1,
        )

    @staticmethod
    def _primary_id(unit: _Unit) -> str:
        """The unit member that owns it: the largest drawing, then id order."""
        return min(unit.members, key=lambda item: (-item.width * item.height, item.asset_id)).asset_id

    # -- semantics ------------------------------------------------------------------------
    @staticmethod
    def _roles(beats: list[StoryBeat]) -> tuple[dict[str, str], bool]:
        roles: dict[str, str] = {}
        path_art = False
        for beat in beats:
            context = beat.semantic_context
            entities = {entity.unit_id: entity for entity in (context.entities if context else [])}
            for row in beat.asset_activations:
                entity = entities.get(row.semantic_unit_id or "")
                if entity is None:
                    continue
                roles.setdefault(row.asset_id, str(entity.role or "").upper())
                path_art = path_art or _is_path(entity)
        return roles, path_art

    def _units(self, items: list[LayoutItem], by_id: dict[str, VisualAsset], roles: dict[str, str]) -> list[_Unit]:
        families: dict[str, list[LayoutItem]] = {}
        for item in items:
            asset = by_id.get(item.asset_id)
            families.setdefault(AssetManager.family_id(asset) if asset else item.asset_id, []).append(item)
        units = [
            _Unit(members=members,
                  box=_union([self.footprints.resolve(m, by_id.get(m.asset_id)).box for m in members]),
                  character=any(roles.get(m.asset_id) == "CHARACTER" for m in members),
                  roles={roles.get(m.asset_id, "") for m in members})
            for members in families.values()
        ]
        merged = True
        while merged:  # authored contact (a hand holding a card) makes one rigid unit
            merged = False
            for i, left in enumerate(units):
                for right in units[i + 1:]:
                    if _gap(left.box, right.box) <= CONTACT:
                        left.members += right.members
                        left.box = _union([left.box, right.box])
                        left.character = left.character or right.character
                        left.roles |= right.roles
                        units.remove(right)
                        merged = True
                        break
                if merged:
                    break
        return units

    @staticmethod
    def _anchor(objects: list[_Unit], focus_asset_id: str | None, spoken: set[str]) -> _Unit:
        largest = max(objects, key=lambda unit: unit.area)
        contenders = [unit for unit in objects if unit.area >= CONTENDER_SHARE * largest.area]

        def meaning(unit: _Unit) -> tuple[int, float]:
            return (3 * bool(unit.ids & spoken) + 2 * ("PRIMARY" in unit.roles) + ("RESULT" in unit.roles)
                    + (focus_asset_id in unit.ids), unit.area)

        return max(contenders, key=meaning)

    # -- geometry -------------------------------------------------------------------------
    def _place_anchor(self, anchor: _Unit, growth: float, frame: Box,
                      fixed: list[Box]) -> tuple[float, Box] | None:
        cx, cy = anchor.centre
        fx, fy = (frame[0] + frame[2]) / 2, (frame[1] + frame[3]) / 2
        scale = growth
        while scale >= 1.0 - 1e-9:
            for pull in (CENTRE_PULL, CENTRE_PULL / 2, 0.0):
                box = _box_at(cx + (fx - cx) * pull, cy + (fy - cy) * pull,
                              anchor.width * scale, anchor.height * scale)
                box = _inside(box, frame)
                if box is not None and not any(_gap(box, other) < GAP for other in fixed):
                    return scale, box
            scale -= 0.05
        return None

    @staticmethod
    def _place_satellite(unit: _Unit, scale: float, old_anchor: tuple[float, float],
                         new_anchor: tuple[float, float], frame: Box,
                         obstacles: list[Box]) -> Box | None:
        # The references cluster small symbols right beside their anchor (the ticks around
        # the magnet): a satellite keeps its side of the anchor and takes the closest free
        # spot along that direction, so the idea reads as one group and frees room for type.
        dx, dy = unit.centre[0] - old_anchor[0], unit.centre[1] - old_anchor[1]
        distance = hypot(dx, dy)
        base = atan2(dy, dx) if distance > 1e-6 else 0.0
        width, height = unit.width * scale, unit.height * scale
        for angle in _ANGLES:
            theta = base + radians(angle)
            for step in range(_RADIAL_STEPS + 1):
                r = step * _RADIAL_STEP
                box = _inside(_box_at(new_anchor[0] + cos(theta) * r, new_anchor[1] + sin(theta) * r,
                                      width, height), frame)
                if box is not None and all(_gap(box, other) >= GAP for other in obstacles):
                    return box
        return None

    @staticmethod
    def _order_swapped(units: list[_Unit], placed: dict[int, tuple[float, Box]]) -> bool:
        for i, a in enumerate(units):
            for b in units[i + 1:]:
                (ax, ay), (bx, by) = a.centre, b.centre
                (nax, nay), (nbx, nby) = _centre(placed[id(a)][1]), _centre(placed[id(b)][1])
                if abs(ax - bx) > ORDER_MARGIN and (ax - bx) * (nax - nbx) < 0:
                    return True
                if abs(ay - by) > ORDER_MARGIN and (ay - by) * (nay - nby) < 0:
                    return True
        return False


def _union(boxes: list[Box]) -> Box:
    return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))


def _centre(box: Box) -> tuple[float, float]:
    return ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)


def _box_at(cx: float, cy: float, width: float, height: float) -> Box:
    return (cx - width / 2, cy - height / 2, cx + width / 2, cy + height / 2)


def _inside(box: Box, frame: Box) -> Box | None:
    """Shift ``box`` into ``frame``; None when it cannot fit."""
    width, height = box[2] - box[0], box[3] - box[1]
    if width > frame[2] - frame[0] + 1e-9 or height > frame[3] - frame[1] + 1e-9:
        return None
    dx = max(frame[0] - box[0], 0.0) + min(frame[2] - box[2], 0.0)
    dy = max(frame[1] - box[1], 0.0) + min(frame[3] - box[3], 0.0)
    return (box[0] + dx, box[1] + dy, box[2] + dx, box[3] + dy)


def _gap(a: Box, b: Box) -> float:
    """Clearance between two boxes (negative when they overlap)."""
    gx = max(a[0], b[0]) - min(a[2], b[2])
    gy = max(a[1], b[1]) - min(a[3], b[3])
    if gx < 0 and gy < 0:
        return max(gx, gy)
    return hypot(max(gx, 0.0), max(gy, 0.0))
