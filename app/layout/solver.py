from __future__ import annotations

from collections import defaultdict
from itertools import permutations

from app.assets import AssetManager
from app.layout.footprint import AlphaFootprintResolver, AssetFootprint
from app.models import CompositionBeat, LayoutItem, VisualAsset
from app.reference import HexaVisualProfile


class ConstraintLayoutSolver:
    """Preserve authored geometry and repair only unsafe layouts.

    OR-Tools is used when available to assign semantic families to safe reference zones;
    a deterministic exhaustive assignment is used as the exact fallback for <=4 groups.
    """

    def __init__(
        self,
        profile: HexaVisualProfile | None = None,
        footprints: AlphaFootprintResolver | None = None,
    ) -> None:
        self.profile = profile or HexaVisualProfile.production()
        self.footprints = footprints or AlphaFootprintResolver()

    def solve(self, beat: CompositionBeat, assets: list[VisualAsset]) -> CompositionBeat:
        by_id = {asset.id: asset for asset in assets}
        groups = self._groups(beat.items, by_id)
        violations = self.inspect(beat.items, by_id)
        if not violations and len(groups) <= self.profile.max_standard_elements:
            evidence = [*beat.state_evidence, "layout:authored_preserved"]
            return beat.model_copy(update={"state_evidence": list(dict.fromkeys(evidence))})

        repaired = self._repair(beat.items, by_id, groups)
        evidence = [
            *beat.state_evidence,
            "layout:constraint_repair",
            *(f"layout_violation:{row}" for row in violations[:6]),
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
            role = (asset.role if asset else "").lower()
            narrator = "narrator" in role or role in {"main_character", "main_narrator"}
            left = 0.0 if narrator else self.profile.safe_left
            right = 1.0 if narrator else self.profile.safe_right
            top = 0.0 if narrator else self.profile.safe_top
            bottom = 1.0 if narrator else self.profile.safe_bottom
            if x0 < left - 0.012 or x1 > right + 0.012 or y0 < top - 0.012 or y1 > bottom + 0.012:
                issues.append(f"safe_margin:{item.asset_id}")

        for index, (item_a, asset_a, foot_a) in enumerate(resolved):
            for item_b, asset_b, foot_b in resolved[index + 1:]:
                if asset_a and asset_b and AssetManager.family_id(asset_a) == AssetManager.family_id(asset_b):
                    continue
                ratio = self._overlap_ratio(foot_a.box, foot_b.box)
                if ratio > self.profile.catastrophic_overlap_ratio:
                    issues.append(f"overlap:{item_a.asset_id}:{item_b.asset_id}:{ratio:.3f}")
        return issues

    def _repair(
        self,
        items: list[LayoutItem],
        by_id: dict[str, VisualAsset],
        groups: dict[str, list[LayoutItem]],
    ) -> list[LayoutItem]:
        family_ids = list(groups)
        if len(family_ids) > self.profile.max_standard_elements:
            family_ids = family_ids[: self.profile.max_standard_elements]

        centers = {
            family_id: self._group_center(groups[family_id], by_id)
            for family_id in family_ids
        }
        zones = self._zones(len(family_ids))
        assignment = self._assign(family_ids, centers, zones)

        output: list[LayoutItem] = []
        for family_id in family_ids:
            members = groups[family_id]
            old_x, old_y = centers[family_id]
            new_x, new_y = assignment[family_id]
            dx = new_x - old_x
            dy = new_y - old_y
            for item in members:
                output.append(item.model_copy(update={
                    "x": max(0.02, min(0.98, item.x + dx)),
                    "y": max(0.03, min(0.97, item.y + dy)),
                    "placement_source": "constraint_solver",
                }))
        return sorted(output, key=lambda row: row.z, reverse=False)

    def _groups(
        self,
        items: list[LayoutItem],
        by_id: dict[str, VisualAsset],
    ) -> dict[str, list[LayoutItem]]:
        grouped: dict[str, list[LayoutItem]] = defaultdict(list)
        for item in items:
            asset = by_id.get(item.asset_id)
            family = AssetManager.family_id(asset) if asset else item.asset_id
            grouped[family].append(item)
        return dict(grouped)

    def _group_center(
        self,
        items: list[LayoutItem],
        by_id: dict[str, VisualAsset],
    ) -> tuple[float, float]:
        boxes = [self.footprints.resolve(item, by_id.get(item.asset_id)).box for item in items]
        x0 = min(box[0] for box in boxes)
        y0 = min(box[1] for box in boxes)
        x1 = max(box[2] for box in boxes)
        y1 = max(box[3] for box in boxes)
        return ((x0 + x1) / 2, (y0 + y1) / 2)

    def _assign(
        self,
        family_ids: list[str],
        centers: dict[str, tuple[float, float],
        zones: list[tuple[float, float],
    ) -> dict[str, tuple[float, float]]:
        try:
            from ortools.sat.python import cp_model
        except ImportError:
            return self._assign_exhaustive(family_ids, centers, zones)

        model = cp_model.CpModel()
        choices: dict[tuple[int, int], object] = {}
        for i in range(len(family_ids)):
            for j in range(len(zones)):
                choices[i, j] = model.new_bool_var(f"family_{i}_zone_{j}")
            model.add(sum(choices[i, j] for j in range(len(zones))) == 1)
        for j in range(len(zones)):
            model.add(sum(choices[i, j] for i in range(len(family_ids))) <= 1)

        costs = []
        for i, family in enumerate(family_ids):
            cx, cy = centers[family]
            for j, (zx, zy) in enumerate(zones):
                cost = int(round(((cx - zx) ** 2 + (cy - zy) ** 2) * 100_000))
                costs.append(cost * choices[i, j])
        model.minimize(sum(costs))
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = 0.15
        status = solver.solve(model)
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            return self._assign_exhaustive(family_ids, centers, zones)
        return {
            family: zones[next(j for j in range(len(zones)) if solver.value(choices[i, j]))]
            for i, family in enumerate(family_ids)
        }

    @staticmethod
    def _assign_exhaustive(
        family_ids: list[str],
        centers: dict[str, tuple[float, float]],
        zones: list[tuple[float, float]],
    ) -> dict[str, tuple[float, float]]:
        best = None
        best_cost = float("inf")
        for candidate in permutations(zones, len(family_ids)):
            cost = 0.0
            for family, zone in zip(family_ids, candidate):
                cx, cy = centers[family]
                cost += (cx - zone[0]) ** 2 + (cy - zone[1]) ** 2
            if cost < best_cost:
                best_cost = cost
                best = candidate
        assert best is not None
        return dict(zip(family_ids, best))

    @staticmethod
    def _zones(count: int) -> list[tuple[float, float]]:
        if count <= 1:
            return [(0.50, 0.52)]
        if count == 2:
            return [(0.29, 0.52), (0.71, 0.52)]
        if count == 3:
            return [(0.28, 0.31), (0.28, 0.72), (0.70, 0.52)]
        return [(0.27, 0.29), (0.73, 0.29), (0.27, 0.71), (0.73, 0.71)]

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
