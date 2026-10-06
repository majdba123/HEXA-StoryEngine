from __future__ import annotations

from dataclasses import dataclass
from math import hypot

from app.assets import AssetManager
from app.choreography import ChoreographyDirective, RelationTreatment
from app.layout.connection_geometry import MIN_LENGTH_PX as _MIN_LENGTH_PX
from app.layout.connection_geometry import connector_endpoints as _endpoints
from app.layout.connection_geometry import segment_hits_rect as _segment_hits_rect
from app.layout.footprint import AlphaFootprintResolver
from app.models import LayoutItem, VisualAsset
from app.reference import HexaVisualProfile
from app.targets import active_target

Rect = tuple[float, float, float, float]

STAGED_PLACEMENT_SOURCE = "authored_semantic_staging"
_ACTIVE_TREATMENTS = frozenset({RelationTreatment.FOCUS_HANDOFF, RelationTreatment.INTERACTION})
# Hard ceiling per axis (normalized frame units), never a target: candidates are tried
# smallest-first, so the first effective one is the minimal intervention.
MAX_SHIFT = 0.04
_STEPS = tuple(round(MAX_SHIFT * n / 8, 6) for n in range(1, 9))
_DIRECTIONS = ((1.0, 0.0), (-1.0, 0.0), (0.0, 1.0), (0.0, -1.0))
# A fixed relation must clear third elements by this much spare room.
_MATERIAL_MARGIN_PX = 12.0
# Smallest-first search always lands right at the pass bar, so the bar itself must mean
# "clearly readable": a fixed relation needs twice the connector's minimum length.
_MATERIAL_LENGTH_PX = 2.0 * _MIN_LENGTH_PX
# Minimum visible-alpha clearance between unrelated families (no important touching).
_CLEARANCE_PX = 16.0
# Staging must not trade crowding: an unrelated neighbour may never end up tighter to
# the moved family than min(its authored gap, the connector's own readable length).
_NEIGHBOUR_SPACING_PX = _MIN_LENGTH_PX


@dataclass(frozen=True, slots=True)
class StagingResult:
    items: list[LayoutItem]
    evidence: str


class SemanticStagingPlanner:
    """Sprint 4.3: conservative semantic staging over the authored scene geometry.

    Authored geometry is candidate zero and wins by default. Choreography's resolved
    relation decisions are the only semantic evidence; nothing is reclassified here. A
    scene changes only when an active authored relation is unreadable for a geometric
    reason the existing connector gate reports (participants crowded, or the relation
    crossing a third element) and one rigid translation of a single free asset family,
    at most ``MAX_SHIFT`` on one axis, makes every such relation clearly readable while
    keeping the safe frame, clearance, topology, unrelated neighbour spacing and every
    already-readable relation. Marginal gains keep baseline. The decision is made once
    per scene; size, aspect and z never change.
    """

    def __init__(
        self,
        *,
        profile: HexaVisualProfile | None = None,
        footprints: AlphaFootprintResolver | None = None,
    ) -> None:
        self.profile = profile or HexaVisualProfile.production()
        self.footprints = footprints or AlphaFootprintResolver()
        reference = active_target()
        self._frame = reference.frame
        self._safe_frame = reference.safe_zones.content

    def stage(
        self,
        items: list[LayoutItem],
        assets: list[VisualAsset],
        directives: list[ChoreographyDirective],
    ) -> StagingResult:
        # Pixel rules and the safe frame belong to the target being authored; on the
        # 16:9 reference they are the certified 1920x1080 / HexaVisualProfile values.
        target = active_target()
        self._frame = target.frame
        self._safe_frame = target.safe_zones.content
        by_id = {asset.id: asset for asset in assets}
        if not items or any(not item.placement_source.startswith("authored") for item in items):
            return StagingResult(items, "semantic_staging:baseline:no_authored_geometry")
        ids = {item.asset_id for item in items}
        family_of = {
            item.asset_id: AssetManager.family_id(by_id[item.asset_id])
            if item.asset_id in by_id else item.asset_id
            for item in items
        }
        relations = sorted({
            (row.source_asset_id, row.target_asset_id)
            for directive in directives
            for row in directive.relation_flows
            if row.treatment in _ACTIVE_TREATMENTS
            and row.source_asset_id in ids and row.target_asset_id in ids
            and family_of[row.source_asset_id] != family_of[row.target_asset_id]
        })
        if not relations:
            return StagingResult(items, "semantic_staging:baseline:no_relation_evidence")

        baseline = {item.asset_id: item for item in items}
        defects: dict[tuple[str, str], str] = {}
        readable: list[tuple[str, str]] = []
        for pair in relations:
            reason = self._defect(pair, baseline)
            if reason is None:
                if self._readable(pair, baseline):
                    readable.append(pair)
            elif reason != "authored_contact":
                defects[pair] = reason
        if not defects:
            return StagingResult(items, "semantic_staging:baseline:readable")

        members: dict[str, list[str]] = {}
        for item in items:
            members.setdefault(family_of[item.asset_id], []).append(item.asset_id)
        feet = {
            family: self._union(ids_, baseline, by_id) for family, ids_ in members.items()
        }
        leaders = {d.primary_asset_id for d in directives if d.primary_asset_id}
        movable = sorted(
            family for family in self._involved(defects, baseline, family_of)
            if self._free(family, feet)
        )
        partners: dict[str, set[str]] = {}
        for source, target in relations:
            partners.setdefault(family_of[source], set()).add(family_of[target])
            partners.setdefault(family_of[target], set()).add(family_of[source])
        candidates = sorted(
            (
                hypot(step * dx * self._frame[0], step * dy * self._frame[1]),
                any(asset_id in leaders for asset_id in members[family]),
                family,
                index,
                step * dx,
                step * dy,
            )
            for family in movable
            for step in _STEPS
            for index, (dx, dy) in enumerate(_DIRECTIONS)
        )
        # Rejections are audited by kind: unsafe (frame/clearance/topology/neighbours),
        # marginal (readable but not clearly), ineffective, or regressing another relation.
        rejected = {"unsafe": 0, "marginal": 0, "ineffective": 0, "regression": 0}
        for _cost, _leader, family, _index, dx, dy in candidates:
            moved = self._translate(members[family], baseline, dx, dy)
            if not self._safe(family, members, moved, feet, by_id, partners.get(family, set())):
                rejected["unsafe"] += 1
                continue
            if not all(self._material(pair, moved) for pair in defects):
                kind = "marginal" if all(self._readable(p, moved) for p in defects) else "ineffective"
                rejected[kind] += 1
                continue
            if not all(self._readable(pair, moved) for pair in readable):
                rejected["regression"] += 1
                continue
            reason = "+".join(sorted(set(defects.values())))
            return StagingResult(
                [moved[item.asset_id] for item in items],
                f"semantic_staging:adjusted:{reason}:{family}:{dx:+.4f},{dy:+.4f}"
                f":rejected={sum(rejected.values())}",
            )
        if not movable:
            kept = "no_free_family"
        elif len(defects) > 1:
            kept = "conflicting_relations"
        elif rejected["marginal"]:
            kept = "marginal_improvement"
        else:
            kept = "no_safe_improvement"
        audit = ",".join(f"{key}{value}" for key, value in rejected.items())
        return StagingResult(items, f"semantic_staging:baseline:{kept}:rejected={audit}")

    # -- relation readability (the Sprint 4.1 connector gate, on layout boxes) ---------
    def _defect(self, pair: tuple[str, str], layout: dict[str, LayoutItem]) -> str | None:
        source, target = (self._px(layout[asset_id]) for asset_id in pair)
        if self._gap(source, target) <= 0.0:
            return "authored_contact"  # touching/overlapping art is intentional contact
        if _endpoints(source, target, []) is None:
            return "participant_crowding"
        if _endpoints(source, target, self._others(pair, layout)) is None:
            return "relation_crossing"
        return None

    def _material(self, pair: tuple[str, str], layout: dict[str, LayoutItem]) -> bool:
        return self._readable(
            pair, layout, margin=_MATERIAL_MARGIN_PX, length=_MATERIAL_LENGTH_PX,
        )

    def _readable(
        self,
        pair: tuple[str, str],
        layout: dict[str, LayoutItem],
        *,
        margin: float = 0.0,
        length: float = _MIN_LENGTH_PX,
    ) -> bool:
        source, target = (self._px(layout[asset_id]) for asset_id in pair)
        others = [
            (r[0] - margin, r[1] - margin, r[2] + margin, r[3] + margin)
            for r in self._others(pair, layout)
        ]
        points = _endpoints(source, target, others)
        if points is None:
            return False
        (x0, y0), (x1, y1) = points
        return hypot(x1 - x0, y1 - y0) >= length

    def _involved(
        self,
        defects: dict[tuple[str, str], str],
        layout: dict[str, LayoutItem],
        family_of: dict[str, str],
    ) -> set[str]:
        families: set[str] = set()
        for pair, reason in defects.items():
            families.update(family_of[asset_id] for asset_id in pair)
            if reason != "relation_crossing":
                continue
            points = _endpoints(*(self._px(layout[asset_id]) for asset_id in pair), [])
            if points is None:
                continue
            families.update(
                family_of[asset_id]
                for asset_id, item in layout.items()
                if asset_id not in pair and _segment_hits_rect(*points, self._px(item))
            )
        return families

    def _others(self, pair: tuple[str, str], layout: dict[str, LayoutItem]) -> list[Rect]:
        return [self._px(item) for asset_id, item in sorted(layout.items()) if asset_id not in pair]

    # -- hard constraints ----------------------------------------------------------------
    def _free(self, family: str, feet: dict[str, Rect]) -> bool:
        """Only a family not in authored contact with any other family may move."""
        return all(
            self._gap(feet[family], foot) >= _CLEARANCE_PX
            for other, foot in feet.items() if other != family
        )

    def _safe(
        self,
        family: str,
        members: dict[str, list[str]],
        moved: dict[str, LayoutItem],
        feet: dict[str, Rect],
        by_id: dict[str, VisualAsset],
        partners: set[str],
    ) -> bool:
        foot = self._union(members[family], moved, by_id)
        p = self._safe_frame
        width, height = self._frame
        if (
            foot[0] < p.left * width or foot[2] > p.right * width
            or foot[1] < p.top * height or foot[3] > p.bottom * height
        ):
            return False
        before = _center(feet[family])
        after = _center(foot)
        for other, other_foot in feet.items():
            if other == family:
                continue
            gap = self._gap(foot, other_foot)
            if gap < _CLEARANCE_PX:
                return False
            if other not in partners and gap < min(
                self._gap(feet[family], other_foot), _NEIGHBOUR_SPACING_PX,
            ):
                return False
            anchor = _center(other_foot)
            for axis in (0, 1):  # topology: no left/right or above/below swap
                was, now = before[axis] - anchor[axis], after[axis] - anchor[axis]
                if abs(was) > 1e-9 and was * now <= 0.0:
                    return False
        return True

    # -- geometry helpers ------------------------------------------------------------------
    @staticmethod
    def _translate(
        ids: list[str], layout: dict[str, LayoutItem], dx: float, dy: float,
    ) -> dict[str, LayoutItem]:
        moved = dict(layout)
        for asset_id in ids:  # one rigid delta for every member of the family
            item = layout[asset_id]
            moved[asset_id] = item.model_copy(update={
                "x": item.x + dx,
                "y": item.y + dy,
                "placement_source": STAGED_PLACEMENT_SOURCE,
            })
        return moved

    def _union(
        self, ids: list[str], layout: dict[str, LayoutItem], by_id: dict[str, VisualAsset],
    ) -> Rect:
        boxes = [self.footprints.resolve(layout[a], by_id.get(a)).box for a in ids]
        width, height = self._frame
        return (
            min(b[0] for b in boxes) * width, min(b[1] for b in boxes) * height,
            max(b[2] for b in boxes) * width, max(b[3] for b in boxes) * height,
        )

    def _px(self, item: LayoutItem) -> Rect:
        width, height = self._frame
        return (
            (item.x - item.width / 2) * width, (item.y - item.height / 2) * height,
            (item.x + item.width / 2) * width, (item.y + item.height / 2) * height,
        )

    @staticmethod
    def _gap(a: Rect, b: Rect) -> float:
        return max(b[0] - a[2], a[0] - b[2], b[1] - a[3], a[1] - b[3])


def _center(rect: Rect) -> tuple[float, float]:
    return (rect[0] + rect[2]) / 2.0, (rect[1] + rect[3]) / 2.0

