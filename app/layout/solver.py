from __future__ import annotations

from collections import defaultdict

from app.assets import AssetManager
from app.layout.footprint import AlphaFootprintResolver, AssetFootprint
from app.models import CompositionBeat, LayoutItem, VisualAsset
from app.reference import HexaVisualProfile


class ConstraintLayoutSolver:
    """Validate authored geometry and minimally repair only geometry-less fallbacks.

    A Final Package scene is already composed. Reflowing those authored assets into
    generic zones is destructive, especially after Pass2 creates more movable layers.
    Authored items are therefore spatially immutable. The solver exists only for legacy
    assets that genuinely lack source geometry.
    """

    _OFFSCREEN_TOLERANCE = 0.006
    _FALLBACK_GAP = 0.015
    _MAX_FALLBACK_STEP = 0.08
    _MAX_ITERATIONS = 10

    def __init__(
        self,
        profile: HexaVisualProfile | None = None,
        footprints: AlphaFootprintResolver | None = None,
    ) -> None:
        self.profile = profile or HexaVisualProfile.production()
        self.footprints = footprints or AlphaFootprintResolver()

    def solve(self, beat: CompositionBeat, assets: list[VisualAsset]) -> CompositionBeat:
        by_id = {asset.id: asset for asset in assets}
        issues = self.inspect(beat.items, by_id)
        has_fallback = any(not self._authored(item) for item in beat.items)

        if not has_fallback:
            evidence = [*beat.state_evidence, "layout:authored_geometry_locked"]
            return beat.model_copy(update={"state_evidence": list(dict.fromkeys(evidence))})

        if not issues:
            evidence = [*beat.state_evidence, "layout:fallback_safe"]
            return beat.model_copy(update={"state_evidence": list(dict.fromkeys(evidence))})

        repaired = self._repair_fallback_only(beat.items, by_id)
        remaining = self.inspect(repaired, by_id)
        evidence = [
            *beat.state_evidence,
            "layout:minimal_fallback_repair",
            *(f"layout_violation:{row}" for row in remaining[:6]),
        ]
        return beat.model_copy(update={
            "items": repaired,
            "state_evidence": list(dict.fromkeys(evidence)),
        })

    def inspect(self, items: list[LayoutItem], by_id: dict[str, VisualAsset]) -> list[str]:
        issues: list[str] = []
        resolved: list[tuple[LayoutItem, VisualAsset | None, AssetFootprint]] = []
        for item in items:
            asset = by_id.get(item.asset_id)
            footprint = self.footprints.resolve(item, asset)
            resolved.append((item, asset, footprint))
            x0, y0, x1, y1 = footprint.box

            if self._authored(item):
                if (
                    x0 < -self._OFFSCREEN_TOLERANCE
                    or y0 < -self._OFFSCREEN_TOLERANCE
                    or x1 > 1.0 + self._OFFSCREEN_TOLERANCE
                    or y1 > 1.0 + self._OFFSCREEN_TOLERANCE
                ):
                    issues.append(f"authored_offscreen:{item.asset_id}")
            else:
                if (
                    x0 < self.profile.safe_left - 0.012
                    or x1 > self.profile.safe_right + 0.012
                    or y0 < self.profile.safe_top - 0.012
                    or y1 > self.profile.safe_bottom + 0.012
                ):
                    issues.append(f"fallback_safe_margin:{item.asset_id}")

        for index, (item_a, asset_a, foot_a) in enumerate(resolved):
            for item_b, asset_b, foot_b in resolved[index + 1:]:
                if asset_a and asset_b and AssetManager.family_id(asset_a) == AssetManager.family_id(asset_b):
                    continue
                if self._authored(item_a) and self._authored(item_b):
                    continue
                ratio = self._overlap_ratio(foot_a.box, foot_b.box)
                if ratio > self.profile.catastrophic_overlap_ratio:
                    issues.append(f"fallback_overlap:{item_a.asset_id}:{item_b.asset_id}:{ratio:.3f}")
        return issues

    def _repair_fallback_only(
        self,
        items: list[LayoutItem],
        by_id: dict[str, VisualAsset],
    ) -> list[LayoutItem]:
        current = {item.asset_id: item for item in items}
        family_members: dict[str, list[str]] = defaultdict(list)
        for item in items:
            asset = by_id.get(item.asset_id)
            family = AssetManager.family_id(asset) if asset else item.asset_id
            family_members[family].append(item.asset_id)

        locked = {
            family
            for family, ids in family_members.items()
            if all(self._authored(current[asset_id]) for asset_id in ids)
        }

        for _ in range(self._MAX_ITERATIONS):
            changed = False
            for family, ids in family_members.items():
                if family in locked:
                    continue
                dx, dy = self._safe_frame_shift(ids, current, by_id)
                if abs(dx) > 1e-9 or abs(dy) > 1e-9:
                    self._translate(ids, current, dx, dy)
                    changed = True

            families = list(family_members)
            for i, family_a in enumerate(families):
                for family_b in families[i + 1:]:
                    if family_a in locked and family_b in locked:
                        continue
                    box_a = self._family_box(family_members[family_a], current, by_id)
                    box_b = self._family_box(family_members[family_b], current, by_id)
                    if self._overlap_ratio(box_a, box_b) <= self.profile.catastrophic_overlap_ratio:
                        continue
                    shift_a, shift_b = self._separation_shifts(
                        box_a,
                        box_b,
                        movable_a=family_a not in locked,
                        movable_b=family_b not in locked,
                    )
                    if shift_a != (0.0, 0.0):
                        self._translate(family_members[family_a], current, *shift_a)
                        changed = True
                    if shift_b != (0.0, 0.0):
                        self._translate(family_members[family_b], current, *shift_b)
                        changed = True
            if not changed:
                break

        return [current[item.asset_id] for item in items]

    def _safe_frame_shift(
        self,
        ids: list[str],
        current: dict[str, LayoutItem],
        by_id: dict[str, VisualAsset],
    ) -> tuple[float, float]:
        x0, y0, x1, y1 = self._family_box(ids, current, by_id)
        dx = 0.0
        dy = 0.0
        if x0 < self.profile.safe_left:
            dx = self.profile.safe_left - x0
        elif x1 > self.profile.safe_right:
            dx = self.profile.safe_right - x1
        if y0 < self.profile.safe_top:
            dy = self.profile.safe_top - y0
        elif y1 > self.profile.safe_bottom:
            dy = self.profile.safe_bottom - y1
        return self._cap(dx), self._cap(dy)

    def _family_box(
        self,
        ids: list[str],
        current: dict[str, LayoutItem],
        by_id: dict[str, VisualAsset],
    ) -> tuple[float, float, float, float]:
        boxes = [
            self.footprints.resolve(current[asset_id], by_id.get(asset_id)).box
            for asset_id in ids
        ]
        return (
            min(box[0] for box in boxes),
            min(box[1] for box in boxes),
            max(box[2] for box in boxes),
            max(box[3] for box in boxes),
        )

    def _separation_shifts(
        self,
        a: tuple[float, float, float, float],
        b: tuple[float, float, float, float],
        *,
        movable_a: bool,
        movable_b: bool,
    ) -> tuple[tuple[float, float], tuple[float, float]]:
        overlap_x = min(a[2], b[2]) - max(a[0], b[0])
        overlap_y = min(a[3], b[3]) - max(a[1], b[1])
        if overlap_x <= 0 or overlap_y <= 0:
            return (0.0, 0.0), (0.0, 0.0)
        center_a = ((a[0] + a[2]) / 2, (a[1] + a[3]) / 2)
        center_b = ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)
        if overlap_x <= overlap_y:
            sign = -1.0 if center_a[0] <= center_b[0] else 1.0
            total = min(self._MAX_FALLBACK_STEP, overlap_x + self._FALLBACK_GAP)
            vector = (sign * total, 0.0)
        else:
            sign = -1.0 if center_a[1] <= center_b[1] else 1.0
            total = min(self._MAX_FALLBACK_STEP, overlap_y + self._FALLBACK_GAP)
            vector = (0.0, sign * total)

        if movable_a and movable_b:
            half = (vector[0] / 2, vector[1] / 2)
            return half, (-half[0], -half[1])
        if movable_a:
            return vector, (0.0, 0.0)
        if movable_b:
            return (0.0, 0.0), (-vector[0], -vector[1])
        return (0.0, 0.0), (0.0, 0.0)

    @staticmethod
    def _translate(
        ids: list[str],
        current: dict[str, LayoutItem],
        dx: float,
        dy: float,
    ) -> None:
        for asset_id in ids:
            item = current[asset_id]
            current[asset_id] = item.model_copy(update={
                "x": item.x + dx,
                "y": item.y + dy,
                "placement_source": "minimal_fallback_repair",
            })

    @classmethod
    def _cap(cls, value: float) -> float:
        return max(-cls._MAX_FALLBACK_STEP, min(cls._MAX_FALLBACK_STEP, value))

    @staticmethod
    def _authored(item: LayoutItem) -> bool:
        return item.placement_source.startswith("authored")

    @staticmethod
    def _overlap_ratio(a, b) -> float:
        x0 = max(a[0], b[0])
        y0 = max(a[1], b[1])
        x1 = min(a[2], b[2])
        y1 = min(a[3], b[3])
        if x1 <= x0 or y1 <= y0:
            return 0.0
        intersection = (x1 - x0) * (y1 - y0)
        area_a = max(1e-9, (a[2] - a[0]) * (a[3] - a[1]))
        area_b = max(1e-9, (b[2] - b[0]) * (b[3] - b[1]))
        return intersection / min(area_a, area_b)
