from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image

from app.models import SceneSource, VisualAsset


Box = tuple[float, float, float, float]


@dataclass(frozen=True, slots=True)
class VisualIdentityMatch:
    semantic_asset_id: str
    real_asset_id: str
    score: float
    runner_up_score: float | None
    margin: float | None
    source: str
    locator: Box | None = None


@dataclass(frozen=True, slots=True)
class VisualIdentityBinding:
    matches: dict[str, VisualIdentityMatch]
    multi_matches: dict[str, tuple[VisualIdentityMatch, ...]]
    locator_semantic_ids: frozenset[str]
    unresolved_locator_ids: frozenset[str]

    @property
    def has_incomplete_locator_binding(self) -> bool:
        return bool(self.unresolved_locator_ids)

    def matches_for(self, semantic_asset_id: str) -> tuple[VisualIdentityMatch, ...]:
        single = self.matches.get(semantic_asset_id)
        if single is not None:
            return (single,)
        return self.multi_matches.get(semantic_asset_id, ())


@dataclass(frozen=True, slots=True)
class _Proposal:
    semantic_asset_id: str
    real_asset_id: str
    score: float
    runner_up_score: float | None
    margin: float | None
    locator: Box


@dataclass(frozen=True, slots=True)
class _MultiProposal:
    semantic_asset_id: str
    real_asset_ids: tuple[str, ...]
    score: float
    locator_coverage: float
    union_score: float
    locator: Box


class VisualIdentityBinder:
    """Bind semantic Final Package intents to already-extracted real cutouts.

    This component never creates, crops, segments, moves, or relayouts an asset. It only
    resolves identity using authored visual provenance. Semantic meaning stays in the
    Final Package; source geometry stays in Pass1/Pass2. When evidence is ambiguous the
    binder abstains rather than letting size/order heuristics override a visual locator.
    """

    _MIN_SCORE = 0.60
    _MIN_MARGIN = 0.065
    _MIN_ALPHA = 10

    # A locator may intentionally describe one visual unit made of several detached
    # cutouts. This is only accepted after one-to-one matching abstains, and only when
    # multiple distinct cutouts are strongly contained by the authored locator and
    # their union reproduces the locator geometry. These guards prevent two nearly
    # duplicate/overlapping candidates from being misread as a legitimate visual unit.
    _MULTI_MIN_REAL_CONTAINMENT = 0.88
    _MULTI_MIN_PRIMARY_LOCATOR_SHARE = 0.015
    _MULTI_PRIMARY_SHARE_RATIO = 0.18
    _MULTI_MIN_UNION_SCORE = 0.80
    _MULTI_MIN_LOCATOR_COVERAGE = 0.18
    _MULTI_MAX_PAIR_OVERLAP = 0.35
    _MULTI_SATELLITE_MIN_AREA_RATIO = 0.05
    _MULTI_SATELLITE_MIN_LOCATOR_SHARE = 0.0015

    def __init__(self) -> None:
        self._alpha_cache: dict[Path, Box | None] = {}

    def bind(
        self,
        *,
        scene: SceneSource,
        semantic_assets: list[dict[str, Any]],
        assets: list[VisualAsset],
    ) -> VisualIdentityBinding:
        unit_by_id = {
            str(unit.get("unit_id")): unit
            for unit in scene.units
            if isinstance(unit, dict) and unit.get("unit_id")
        }
        asset_by_id = {asset.id: asset for asset in assets}
        eligible = [
            asset for asset in assets
            if asset.can_animate_independently
            and (asset.role or "").casefold() not in {"background", "decorative"}
        ]
        real_boxes = {
            asset.id: box
            for asset in eligible
            if (box := self._asset_box(asset)) is not None
        }

        matches: dict[str, VisualIdentityMatch] = {}
        multi_matches: dict[str, tuple[VisualIdentityMatch, ...]] = {}
        reserved: set[str] = set()
        locator_rows: dict[str, tuple[dict[str, Any], Box]] = {}

        # Exact authored real-asset identity, when it exists, remains strongest.
        for row in semantic_assets:
            if not isinstance(row, dict):
                continue
            semantic_id = str(row.get("asset_id") or "").strip()
            if not semantic_id:
                continue
            locator_raw = row.get("visual_locator")
            if locator_raw is None:
                locator_raw = unit_by_id.get(semantic_id, {}).get("visual_locator")
            locator = self._locator_box(locator_raw)
            if locator is not None:
                locator_rows[semantic_id] = (row, locator)
            if semantic_id in asset_by_id and semantic_id not in reserved:
                matches[semantic_id] = VisualIdentityMatch(
                    semantic_asset_id=semantic_id,
                    real_asset_id=semantic_id,
                    score=1.0,
                    runner_up_score=None,
                    margin=None,
                    source="explicit_real_asset_id",
                    locator=locator,
                )
                reserved.add(semantic_id)

        unresolved = {
            semantic_id
            for semantic_id in locator_rows
            if semantic_id not in matches
        }

        # Assign the most certain locator first. Re-ranking after every reservation
        # prevents package ordering from deciding identity when several icons are close.
        while unresolved:
            proposals: list[_Proposal] = []
            for semantic_id in sorted(unresolved):
                row, locator = locator_rows[semantic_id]
                ranked = self._rank_candidates(
                    locator=locator,
                    semantic_row=row,
                    real_boxes=real_boxes,
                    assets=asset_by_id,
                    reserved=reserved,
                    matches=matches,
                )
                if not ranked:
                    continue
                top_id, top_score = ranked[0]
                runner_up = ranked[1][1] if len(ranked) > 1 else None
                margin = top_score - runner_up if runner_up is not None else top_score
                if top_score < self._MIN_SCORE or margin < self._MIN_MARGIN:
                    continue
                proposals.append(_Proposal(
                    semantic_asset_id=semantic_id,
                    real_asset_id=top_id,
                    score=top_score,
                    runner_up_score=runner_up,
                    margin=margin,
                    locator=locator,
                ))

            if not proposals:
                break

            chosen = max(
                proposals,
                key=lambda row: (
                    row.margin if row.margin is not None else row.score,
                    row.score,
                    row.semantic_asset_id,
                ),
            )
            matches[chosen.semantic_asset_id] = VisualIdentityMatch(
                semantic_asset_id=chosen.semantic_asset_id,
                real_asset_id=chosen.real_asset_id,
                score=chosen.score,
                runner_up_score=chosen.runner_up_score,
                margin=chosen.margin,
                source="visual_locator",
                locator=chosen.locator,
            )
            reserved.add(chosen.real_asset_id)
            unresolved.remove(chosen.semantic_asset_id)

        # Some semantic intents intentionally represent a visual unit composed of
        # several detached cutouts (for example a row of cards or network nodes). The
        # package contract explicitly permits ZERO_OR_ONE_OR_MANY real cutouts per
        # semantic intent. Resolve that cardinality only after the stricter one-to-one
        # path abstains; never lower the single-match ambiguity thresholds.
        while unresolved:
            proposals: list[_MultiProposal] = []
            for semantic_id in sorted(unresolved):
                _row, locator = locator_rows[semantic_id]
                proposal = self._multi_candidate_proposal(
                    semantic_asset_id=semantic_id,
                    locator=locator,
                    real_boxes=real_boxes,
                    reserved=reserved,
                )
                if proposal is not None:
                    proposals.append(proposal)
            if not proposals:
                break

            chosen = max(
                proposals,
                key=lambda row: (
                    row.score,
                    row.union_score,
                    row.locator_coverage,
                    row.semantic_asset_id,
                ),
            )
            members = tuple(
                VisualIdentityMatch(
                    semantic_asset_id=chosen.semantic_asset_id,
                    real_asset_id=real_id,
                    score=chosen.score,
                    runner_up_score=None,
                    margin=None,
                    source="visual_locator_multi",
                    locator=chosen.locator,
                )
                for real_id in chosen.real_asset_ids
            )
            multi_matches[chosen.semantic_asset_id] = members
            reserved.update(chosen.real_asset_ids)
            unresolved.remove(chosen.semantic_asset_id)

        locator_ids = frozenset(locator_rows)
        resolved_locator_ids = set(matches) | set(multi_matches)
        return VisualIdentityBinding(
            matches=matches,
            multi_matches=multi_matches,
            locator_semantic_ids=locator_ids,
            unresolved_locator_ids=frozenset(locator_ids - resolved_locator_ids),
        )

    def _multi_candidate_proposal(
        self,
        *,
        semantic_asset_id: str,
        locator: Box,
        real_boxes: dict[str, Box],
        reserved: set[str],
    ) -> _MultiProposal | None:
        locator_area = self._area(locator)
        if locator_area <= 0.0:
            return None

        contained: list[tuple[str, Box, float, float]] = []
        for real_id, real_box in real_boxes.items():
            if real_id in reserved:
                continue
            real_area = self._area(real_box)
            if real_area <= 0.0:
                continue
            intersection = self._intersection(locator, real_box)
            real_containment = intersection / real_area
            locator_share = intersection / locator_area
            if real_containment >= self._MULTI_MIN_REAL_CONTAINMENT:
                contained.append((real_id, real_box, locator_share, real_area))
        if len(contained) < 2:
            return None

        max_share = max(row[2] for row in contained)
        minimum_primary_share = max(
            self._MULTI_MIN_PRIMARY_LOCATOR_SHARE,
            max_share * self._MULTI_PRIMARY_SHARE_RATIO,
        )
        primary = [row for row in contained if row[2] >= minimum_primary_share]
        if len(primary) < 2 or self._has_heavy_pair_overlap(primary):
            return None

        union = self._union_box([row[1] for row in primary])
        union_score = self._geometry_score(locator, union)
        coverage = min(1.0, sum(row[2] for row in primary))
        if (
            union_score < self._MULTI_MIN_UNION_SCORE
            or coverage < self._MULTI_MIN_LOCATOR_COVERAGE
        ):
            return None

        ordered_areas = sorted(row[3] for row in primary)
        median_area = ordered_areas[len(ordered_areas) // 2]
        selected = list(primary)
        selected_ids = {row[0] for row in selected}
        for row in contained:
            if row[0] in selected_ids:
                continue
            if (
                row[3] >= median_area * self._MULTI_SATELLITE_MIN_AREA_RATIO
                and row[2] >= self._MULTI_SATELLITE_MIN_LOCATOR_SHARE
            ):
                selected.append(row)

        selected.sort(
            key=lambda row: (self._center(row[1])[0], self._center(row[1])[1], row[0])
        )
        score = min(1.0, 0.78 * union_score + 0.22 * coverage)
        return _MultiProposal(
            semantic_asset_id=semantic_asset_id,
            real_asset_ids=tuple(row[0] for row in selected),
            score=score,
            locator_coverage=coverage,
            union_score=union_score,
            locator=locator,
        )

    @classmethod
    def _has_heavy_pair_overlap(
        cls,
        rows: list[tuple[str, Box, float, float]],
    ) -> bool:
        for index, left in enumerate(rows):
            for right in rows[index + 1:]:
                intersection = cls._intersection(left[1], right[1])
                minimum_area = max(1e-9, min(left[3], right[3]))
                if intersection / minimum_area > cls._MULTI_MAX_PAIR_OVERLAP:
                    return True
        return False

    @staticmethod
    def _union_box(boxes: list[Box]) -> Box:
        return (
            min(box[0] for box in boxes),
            min(box[1] for box in boxes),
            max(box[2] for box in boxes),
            max(box[3] for box in boxes),
        )

    def _rank_candidates(
        self,
        *,
        locator: Box,
        semantic_row: dict[str, Any],
        real_boxes: dict[str, Box],
        assets: dict[str, VisualAsset],
        reserved: set[str],
        matches: dict[str, VisualIdentityMatch],
    ) -> list[tuple[str, float]]:
        parent_semantic_id = str(semantic_row.get("parent_asset_id") or "").strip()
        parent_real_id = (
            matches[parent_semantic_id].real_asset_id
            if parent_semantic_id in matches
            else None
        )
        output: list[tuple[str, float]] = []
        for real_id, real_box in real_boxes.items():
            if real_id in reserved:
                continue
            score = self._geometry_score(locator, real_box)
            if parent_real_id:
                score = min(
                    1.0,
                    score + self._family_bonus(
                        assets[real_id], assets.get(parent_real_id)
                    ),
                )
            output.append((real_id, score))
        output.sort(key=lambda row: (-row[1], row[0]))
        return output

    @classmethod
    def _geometry_score(cls, locator: Box, real: Box) -> float:
        intersection = cls._intersection(locator, real)
        locator_area = cls._area(locator)
        real_area = cls._area(real)
        union = max(1e-9, locator_area + real_area - intersection)
        iou = intersection / union
        containment = intersection / max(1e-9, min(locator_area, real_area))

        lx, ly = cls._center(locator)
        rx, ry = cls._center(real)
        distance = math.hypot(lx - rx, ly - ry)
        locator_w = max(1e-9, locator[2] - locator[0])
        locator_h = max(1e-9, locator[3] - locator[1])
        center_radius = max(0.10, 0.45 * math.hypot(locator_w, locator_h) + 0.06)
        center_score = max(0.0, 1.0 - distance / center_radius)

        area_ratio = max(locator_area, real_area) / max(1e-9, min(locator_area, real_area))
        size_score = max(0.0, 1.0 - math.log(max(1.0, area_ratio), 4.0))

        locator_aspect = locator_w / max(1e-9, locator_h)
        real_w = max(1e-9, real[2] - real[0])
        real_h = max(1e-9, real[3] - real[1])
        real_aspect = real_w / real_h
        aspect_ratio = max(locator_aspect, real_aspect) / max(
            1e-9, min(locator_aspect, real_aspect)
        )
        shape_score = max(0.0, 1.0 - math.log(max(1.0, aspect_ratio), 4.0))

        return max(0.0, min(
            1.0,
            0.36 * iou
            + 0.20 * containment
            + 0.26 * center_score
            + 0.11 * size_score
            + 0.07 * shape_score,
        ))

    @staticmethod
    def _family_bonus(asset: VisualAsset, parent: VisualAsset | None) -> float:
        if parent is None:
            return 0.0
        if asset.parent_asset_id == parent.id:
            return 0.15
        if (
            asset.asset_family_id
            and parent.asset_family_id
            and asset.asset_family_id == parent.asset_family_id
        ):
            return 0.10
        if asset.parent_asset_id and asset.parent_asset_id != parent.id:
            return -0.08
        return 0.0

    def _asset_box(self, asset: VisualAsset) -> Box | None:
        if (
            asset.source_bbox is None
            or asset.source_canvas_width is None
            or asset.source_canvas_height is None
        ):
            return None
        x, y, width, height = asset.source_bbox
        canvas_w = max(1, asset.source_canvas_width)
        canvas_h = max(1, asset.source_canvas_height)
        if width <= 0 or height <= 0:
            return None
        base = (
            x / canvas_w,
            y / canvas_h,
            (x + width) / canvas_w,
            (y + height) / canvas_h,
        )
        if not asset.render_as_family_canvas:
            return base

        # Pass2 family members intentionally share source_bbox so Composition can
        # reassemble them perfectly. Their alpha masks carry the actual child/main
        # identity inside that shared canvas, so use visible alpha only for identity
        # matching while leaving authored geometry untouched everywhere else.
        alpha = self._normalized_alpha_bbox(asset.image_path)
        if alpha is None:
            return base
        ax0, ay0, ax1, ay1 = alpha
        bx0, by0, bx1, by1 = base
        base_w = bx1 - bx0
        base_h = by1 - by0
        return (
            bx0 + base_w * ax0,
            by0 + base_h * ay0,
            bx0 + base_w * ax1,
            by0 + base_h * ay1,
        )

    def _normalized_alpha_bbox(self, path: Path) -> Box | None:
        if path in self._alpha_cache:
            return self._alpha_cache[path]
        result: Box | None = None
        try:
            with Image.open(path) as opened:
                rgba = opened.convert("RGBA")
                alpha = rgba.getchannel("A")
                binary = alpha.point(
                    lambda value: 255 if value >= self._MIN_ALPHA else 0
                )
                bbox = binary.getbbox()
                if bbox is not None:
                    width, height = rgba.size
                    x0, y0, x1, y1 = bbox
                    result = (
                        x0 / max(1, width),
                        y0 / max(1, height),
                        x1 / max(1, width),
                        y1 / max(1, height),
                    )
        except (OSError, ValueError):
            result = None
        self._alpha_cache[path] = result
        return result

    @staticmethod
    def _locator_box(raw: Any) -> Box | None:
        if not isinstance(raw, dict):
            return None
        try:
            cx = float(raw["cx"])
            cy = float(raw["cy"])
            width = float(raw["width"])
            height = float(raw["height"])
        except (KeyError, TypeError, ValueError):
            return None
        if not (
            0.0 <= cx <= 1.0
            and 0.0 <= cy <= 1.0
            and 0.0 < width <= 1.0
            and 0.0 < height <= 1.0
        ):
            return None
        return (
            max(0.0, cx - width / 2),
            max(0.0, cy - height / 2),
            min(1.0, cx + width / 2),
            min(1.0, cy + height / 2),
        )

    @staticmethod
    def _intersection(left: Box, right: Box) -> float:
        x0 = max(left[0], right[0])
        y0 = max(left[1], right[1])
        x1 = min(left[2], right[2])
        y1 = min(left[3], right[3])
        if x1 <= x0 or y1 <= y0:
            return 0.0
        return (x1 - x0) * (y1 - y0)

    @staticmethod
    def _area(box: Box) -> float:
        return max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])

    @staticmethod
    def _center(box: Box) -> tuple[float, float]:
        return ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)
