from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

from app.canonical import CanonicalAsset, CanonicalScene, CanonicalVisualLocator
from app.models import VisualAsset

from .assignment import GlobalMatch, assign_globally


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
    # Locator intents withdrawn because ownership was a near-tie (never guessed).
    ambiguous_ids: frozenset[str] = frozenset()
    # semantic id -> ((cutout id, score), ...) strongest first, for diagnostics.
    candidates: dict[str, tuple[tuple[str, float], ...]] = field(default_factory=dict)
    rivals: dict[str, str] = field(default_factory=dict)

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
    # Assignment weight is (score - floor)^2: one strong match outweighs two weak ones.
    _ASSIGNMENT_WEIGHT_FLOOR = 0.50
    _MIN_ALPHA = 10
    # Event-carrier fallback is deliberately weaker than semantic identity matching.
    # It never claims that a runtime cutout *is* the authored semantic asset.  Story
    # may only use it as a renderable carrier for an authored event when one runtime
    # visual clearly covers the authored locator region better than every alternative.
    # This keeps identity fail-closed while allowing real Final Packages whose locator
    # geometry is approximate rather than pixel-tight to retain semantic timing.
    _PROXY_MIN_LOCATOR_COVERAGE = 0.12
    _PROXY_MIN_COVERAGE_MARGIN = 0.05

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
        scene: CanonicalScene,
        semantic_assets: list[CanonicalAsset],
        assets: list[VisualAsset],
    ) -> VisualIdentityBinding:
        asset_by_id = {asset.id: asset for asset in assets}
        # Presentation roles (``decorative``) are copied from package unit roles and
        # must not hide a cutout that an authored leader/participant/result locates.
        required_ids = frozenset(scene.semantic_carrier_roles)
        eligible = [
            asset for asset in assets
            if asset.can_animate_independently
            and (asset.role or "").casefold() != "background"
        ]
        real_boxes = {
            asset.id: box
            for asset in eligible
            if (box := self._asset_box(asset)) is not None
        }
        decorative_ids = frozenset(
            asset.id for asset in eligible
            if (asset.role or "").casefold() == "decorative"
        )

        matches: dict[str, VisualIdentityMatch] = {}
        multi_matches: dict[str, tuple[VisualIdentityMatch, ...]] = {}
        reserved: set[str] = set()
        locator_rows: dict[str, tuple[CanonicalAsset, Box]] = {}

        # Exact authored real-asset identity, when it exists, remains strongest.
        for row in semantic_assets:
            semantic_id = str(row.asset_id or "").strip()
            if not semantic_id:
                continue
            locator = self._locator_box(row.visual_locator)
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
        optional_boxes = {
            real_id: box for real_id, box in real_boxes.items()
            if real_id not in decorative_ids
        }

        def boxes_for(semantic_id: str) -> dict[str, Box]:
            return real_boxes if semantic_id in required_ids else optional_boxes

        # Scene-global 1:1 ownership. Every locator-bearing intent is scored against
        # every eligible cutout and one assignment is solved for the whole scene, so
        # neither package order nor a locally attractive pick can take a cutout that
        # another intent owns more strongly. The family bonus needs the parent's
        # carrier, so a second pass re-scores with the first pass's assignments.
        candidate_scores: dict[str, dict[str, float]] = {}
        accepted: dict[str, VisualIdentityMatch] = {}
        ambiguous: dict[str, GlobalMatch] = {}
        for _ in range(2):
            parents = {**matches, **accepted}
            candidate_scores = {
                semantic_id: dict(self._rank_candidates(
                    locator=locator_rows[semantic_id][1],
                    semantic_row=locator_rows[semantic_id][0],
                    real_boxes=boxes_for(semantic_id),
                    assets=asset_by_id,
                    reserved=reserved,
                    matches=parents,
                ))
                for semantic_id in sorted(unresolved)
            }
            solved = assign_globally(
                candidate_scores,
                minimum_score=self._MIN_SCORE,
                minimum_margin=self._MIN_MARGIN,
                weight_floor=self._ASSIGNMENT_WEIGHT_FLOOR,
            )
            accepted = {
                semantic_id: VisualIdentityMatch(
                    semantic_asset_id=semantic_id,
                    real_asset_id=row.column,
                    score=row.score,
                    runner_up_score=row.runner_up_score,
                    margin=row.margin,
                    source="visual_locator",
                    locator=locator_rows[semantic_id][1],
                )
                for semantic_id, row in solved.items()
                if row.column is not None and not row.ambiguous
            }
            ambiguous = {
                semantic_id: row for semantic_id, row in solved.items() if row.ambiguous
            }
        matches.update(accepted)
        reserved.update(match.real_asset_id for match in accepted.values())
        unresolved -= set(accepted)

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
                    real_boxes=boxes_for(semantic_id),
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
            ambiguous_ids=frozenset(set(ambiguous) - resolved_locator_ids),
            candidates={
                semantic_id: tuple(sorted(row.items(), key=lambda item: (-item[1], item[0]))[:6])
                for semantic_id, row in candidate_scores.items()
            },
            rivals={
                semantic_id: row.rival for semantic_id, row in ambiguous.items() if row.rival
            },
        )

    def region_carrier(
        self,
        *,
        semantic_asset: CanonicalAsset,
        assets: list[VisualAsset],
    ) -> VisualIdentityMatch | None:
        """Return a conservative render carrier for an unresolved authored locator.

        This is intentionally *not* semantic identity resolution.  The returned source
        is ``visual_locator_region_proxy`` and may only be consumed as a semantic-event
        proxy carrier.  A unique runtime visual must cover enough of the authored
        locator and beat the runner-up by a meaningful coverage margin.  Near-ties
        abstain so the engine never turns ambiguous geometry into fabricated identity.
        """
        locator = self._locator_box(semantic_asset.visual_locator)
        if locator is None:
            return None
        locator_area = self._area(locator)
        if locator_area <= 0.0:
            return None

        ranked: list[tuple[str, float, float]] = []
        for asset in assets:
            if (
                not asset.can_animate_independently
                or (asset.role or "").casefold() in {"background", "decorative"}
            ):
                continue
            real_box = self._asset_box(asset)
            if real_box is None:
                continue
            coverage = self._intersection(locator, real_box) / locator_area
            if coverage <= 0.0:
                continue
            ranked.append((
                asset.id,
                coverage,
                self._geometry_score(locator, real_box),
            ))

        if not ranked:
            return None
        ranked.sort(key=lambda row: (-row[1], -row[2], row[0]))
        top_id, top_coverage, _top_geometry = ranked[0]
        runner_up = ranked[1][1] if len(ranked) > 1 else 0.0
        margin = top_coverage - runner_up
        if (
            top_coverage < self._PROXY_MIN_LOCATOR_COVERAGE
            or margin < self._PROXY_MIN_COVERAGE_MARGIN
        ):
            return None
        return VisualIdentityMatch(
            semantic_asset_id=str(semantic_asset.asset_id),
            real_asset_id=top_id,
            score=min(1.0, top_coverage),
            runner_up_score=(runner_up if len(ranked) > 1 else None),
            margin=margin,
            source="visual_locator_region_proxy",
            locator=locator,
        )

    def contained_carriers(
        self,
        *,
        semantic_asset: CanonicalAsset,
        scene_locators: dict[str, Box],
        assets: list[VisualAsset],
        reserved: set[str],
        standalone: bool = False,
    ) -> tuple[VisualIdentityMatch, ...]:
        """Cutouts that lie inside exactly one authored locator belong to that intent.

        Segmentation may split or merge an authored region, so one authored unit can
        own several cutouts. A candidate must sit almost entirely inside this locator,
        must not be reserved by another proof, and must not also sit wholly inside any
        other authored locator. ``standalone`` (no 1:1 match exists) additionally
        requires the members to explain the authored region (the multi-cutout
        locator-coverage floor); a loose locator is left to the region-proxy path.
        """
        semantic_id = str(semantic_asset.asset_id)
        locator = scene_locators.get(semantic_id)
        if locator is None:
            return ()
        output: list[VisualIdentityMatch] = []
        covered = 0.0
        for asset in sorted(assets, key=lambda row: row.id):
            if (
                asset.id in reserved
                or not asset.can_animate_independently
                or (asset.role or "").casefold() == "background"
            ):
                continue
            box = self._asset_box(asset)
            if box is None or self.contained_share(box, locator) < self._MULTI_MIN_REAL_CONTAINMENT:
                continue
            if any(
                self.contained_share(box, other) >= self._MULTI_MIN_REAL_CONTAINMENT
                for other_id, other in scene_locators.items()
                if other_id != semantic_id
            ):
                # Wholly inside two authored locators: ownership is ambiguous.
                continue
            covered += self._intersection(box, locator)
            output.append(VisualIdentityMatch(
                semantic_asset_id=semantic_id,
                real_asset_id=asset.id,
                score=self.contained_share(box, locator),
                runner_up_score=None,
                margin=None,
                source="visual_locator_contained",
                locator=locator,
            ))
        if standalone and covered / max(1e-9, self._area(locator)) < self._MULTI_MIN_LOCATOR_COVERAGE:
            return ()
        return tuple(output)

    @classmethod
    def contained_share(cls, inner: Box, outer: Box) -> float:
        """Fraction of ``inner`` lying inside ``outer``."""
        area = cls._area(inner)
        return cls._intersection(inner, outer) / area if area > 0 else 0.0

    @classmethod
    def overlap_share(cls, left: Box, right: Box) -> float:
        """Intersection relative to the smaller box."""
        smaller = min(cls._area(left), cls._area(right))
        return cls._intersection(left, right) / smaller if smaller > 0 else 0.0

    def locator_box(self, raw: CanonicalVisualLocator | None) -> Box | None:
        return self._locator_box(raw)

    def asset_box(self, asset: VisualAsset) -> Box | None:
        return self._asset_box(asset)

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
        semantic_row: CanonicalAsset,
        real_boxes: dict[str, Box],
        assets: dict[str, VisualAsset],
        reserved: set[str],
        matches: dict[str, VisualIdentityMatch],
    ) -> list[tuple[str, float]]:
        parent_semantic_id = str(semantic_row.parent_asset_id or "").strip()
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
    def _locator_box(raw: CanonicalVisualLocator | None) -> Box | None:
        if raw is None:
            return None
        try:
            cx = float(raw.cx)
            cy = float(raw.cy)
            width = float(raw.width)
            height = float(raw.height)
        except (TypeError, ValueError):
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
