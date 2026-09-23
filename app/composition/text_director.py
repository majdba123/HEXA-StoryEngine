from __future__ import annotations

from dataclasses import dataclass

from app.composition.footprint import AlphaFootprintResolver
from app.composition.occupancy import VisualOccupancyMap
from app.models import CompositionBeat, LayoutItem, StoryBeat, TextCue, TextLayoutItem, VisualAsset


Box = tuple[float, float, float, float]


@dataclass(frozen=True, slots=True)
class PlacedTextRegion:
    cue_id: str
    start: float
    end: float
    box: Box
    zone: str


@dataclass(frozen=True, slots=True)
class PlacementResult:
    item: TextLayoutItem
    box: Box
    zone: str
    score: float
    visual_overlap: float


@dataclass(frozen=True, slots=True)
class _Candidate:
    x: float
    y: float
    zone: str
    prior: float


@dataclass(frozen=True, slots=True)
class _VisualRegion:
    box: Box
    protected_box: Box
    weight: float


class TextPlacementDirector:
    """Choose authored-looking text positions from the visual geometry of a scene.

    Visual assets keep their Final Package composition. Text has no authored source
    location, so this director searches the scene's negative space and minimizes a
    deterministic visual-energy function. The strongest penalties are artwork occlusion,
    concurrent text collision and unsafe edges. Softer terms preserve semantic proximity,
    scene-to-scene consistency and balanced use of whitespace.
    """

    _SAFE_MARGIN_X = 0.045
    _SAFE_MARGIN_Y = 0.055
    _GRID_STEP_X = 0.02
    _GRID_STEP_Y = 0.0225

    def __init__(self) -> None:
        self.footprints = AlphaFootprintResolver()
        self.occupancy = VisualOccupancyMap()

    def place(
        self,
        *,
        beat: StoryBeat,
        visual: CompositionBeat | None,
        cue: TextCue,
        concurrent_text: list[PlacedTextRegion],
        preferred_zone: str | None,
        assets_by_id: dict[str, VisualAsset] | None = None,
    ) -> PlacementResult:
        anchor = self._anchor(cue, visual)
        asset_map = assets_by_id or {}
        visual_regions = self._visual_regions(beat, visual, asset_map)
        occupancy = self.occupancy.build(visual.items, asset_map) if visual is not None and asset_map else None

        scored = []
        for font_scale in self._font_scales(cue):
            width, height = self.estimated_box(cue, scale=font_scale)
            candidates = self._candidate_field(width, height, anchor)
            for candidate in candidates:
                score_row = self._score_candidate(
                    candidate,
                    width=width,
                    height=height,
                    anchor=anchor,
                    visual_regions=visual_regions,
                    concurrent_text=concurrent_text,
                    preferred_zone=preferred_zone,
                    cue=cue,
                    occupancy=occupancy,
                )
                # Prefer the authored typography size whenever whitespace permits, but
                # reducing text is always safer than moving the Final Package artwork.
                scale_penalty = (1.0 - font_scale) * 1.6
                scored.append((*score_row, font_scale, width))
                scored[-1] = (scored[-1][0] + scale_penalty, *scored[-1][1:])

        best = min(scored, key=lambda row: (row[0], -row[4], row[1].prior, row[1].y, row[1].x))
        score, candidate, box, overlap, font_scale, width = best
        item = TextLayoutItem(
            text_cue_id=cue.id,
            x=candidate.x,
            y=candidate.y,
            max_width=width,
            font_scale=font_scale,
            z=50 + min(20, cue.priority // 5),
            anchor_asset_id=cue.anchor_asset_id,
            placement=candidate.zone,
        )
        return PlacementResult(
            item=item,
            box=box,
            zone=candidate.zone,
            score=score,
            visual_overlap=overlap,
        )

    @staticmethod
    def estimated_box(cue: TextCue, *, scale: float = 1.0) -> tuple[float, float]:
        units = 0.0
        for char in cue.text.strip():
            if char.isspace():
                units += 0.42
            elif char.isdigit():
                units += 0.78
            elif char in ".,:;!?،؛؟-/":
                units += 0.38
            else:
                units += 1.0
        size_factor = 1.10 if cue.priority >= 85 else 1.0
        # Deliberately conservative: libass shaping can make Arabic/mixed numeric
        # phrases wider than a character-count estimate. Slight over-reservation is
        # preferable to a title clipping into artwork.
        width = 0.080 + units * 0.0235 * size_factor
        width = max(0.22, min(0.58, width)) * scale
        height = (0.155 if cue.priority >= 85 else 0.135) * scale
        return width, height

    @staticmethod
    def _font_scales(cue: TextCue) -> tuple[float, ...]:
        # Sparse keywords remain large by default. Dense artwork may force a controlled
        # reduction, but never below a readable production floor.
        return (1.0, 0.90, 0.82, 0.74, 0.68, 0.62, 0.56) if cue.priority >= 85 else (1.0, 0.90, 0.82, 0.76, 0.68, 0.62, 0.56)

    def _candidate_field(
        self,
        width: float,
        height: float,
        anchor: LayoutItem | None,
    ) -> list[_Candidate]:
        x_low = self._SAFE_MARGIN_X + width / 2
        x_high = 1.0 - self._SAFE_MARGIN_X - width / 2
        y_low = self._SAFE_MARGIN_Y + height / 2
        y_high = 1.0 - self._SAFE_MARGIN_Y - height / 2

        candidates: list[_Candidate] = []
        y = y_low
        while y <= y_high + 1e-9:
            x = x_low
            while x <= x_high + 1e-9:
                zone = self._zone_for(x, y)
                candidates.append(_Candidate(x=x, y=y, zone=zone, prior=self._human_prior(x, y)))
                x += self._GRID_STEP_X
            y += self._GRID_STEP_Y

        if anchor is not None:
            candidates.extend(self._anchor_candidates(anchor, width, height, x_low, x_high, y_low, y_high))

        deduped: dict[tuple[int, int, str], _Candidate] = {}
        for candidate in candidates:
            key = (round(candidate.x * 1000), round(candidate.y * 1000), candidate.zone)
            previous = deduped.get(key)
            if previous is None or candidate.prior < previous.prior:
                deduped[key] = candidate
        return list(deduped.values())

    def _anchor_candidates(
        self,
        anchor: LayoutItem,
        width: float,
        height: float,
        x_low: float,
        x_high: float,
        y_low: float,
        y_high: float,
    ) -> list[_Candidate]:
        v_gap = anchor.height / 2 + height / 2 + 0.035
        h_gap = anchor.width / 2 + width / 2 + 0.035
        d_x = anchor.width / 2 + width * 0.38 + 0.025
        d_y = anchor.height / 2 + height * 0.38 + 0.025
        raw = [
            (anchor.x, anchor.y - v_gap, "anchor_top", -0.14),
            (anchor.x, anchor.y + v_gap, "anchor_bottom", -0.10),
            (anchor.x - h_gap, anchor.y, "anchor_left", -0.08),
            (anchor.x + h_gap, anchor.y, "anchor_right", -0.08),
            (anchor.x - d_x, anchor.y - d_y, "anchor_top_left", -0.04),
            (anchor.x + d_x, anchor.y - d_y, "anchor_top_right", -0.04),
            (anchor.x - d_x, anchor.y + d_y, "anchor_bottom_left", -0.02),
            (anchor.x + d_x, anchor.y + d_y, "anchor_bottom_right", -0.02),
        ]
        return [
            _Candidate(
                x=max(x_low, min(x_high, x)),
                y=max(y_low, min(y_high, y)),
                zone=zone,
                prior=prior,
            )
            for x, y, zone, prior in raw
        ]

    def _score_candidate(
        self,
        candidate: _Candidate,
        *,
        width: float,
        height: float,
        anchor: LayoutItem | None,
        visual_regions: list[_VisualRegion],
        concurrent_text: list[PlacedTextRegion],
        preferred_zone: str | None,
        cue: TextCue,
        occupancy,
    ) -> tuple[float, _Candidate, Box, float]:
        box = self._box(candidate.x, candidate.y, width, height)
        score = candidate.prior

        # Pixel occupancy is authoritative for visual collision. Bounding boxes are
        # deliberately only a soft halo because irregular cutouts can contain large
        # negative-space regions that are safe and visually intentional for text.
        actual_overlap = (
            self.occupancy.overlap(occupancy, box).ratio
            if occupancy is not None
            else max(
                (self._intersection_ratio(box, region.box) for region in visual_regions),
                default=0.0,
            )
        )
        if actual_overlap > 0.002:
            score += 180000.0 * actual_overlap
        score += actual_overlap * 12000.0
        for region in visual_regions:
            protected = self._intersection_ratio(box, region.protected_box)
            score += protected * 18.0 * region.weight

        for placed in concurrent_text:
            score += self._intersection_ratio(box, placed.box) * 680.0

        if anchor is not None:
            distance = self._center_distance(candidate.x, candidate.y, anchor.x, anchor.y)
            score += distance * 0.46

        if preferred_zone is not None:
            score += 0.0 if self._zone_family(candidate.zone) == preferred_zone else 0.12

        score += self._edge_penalty(box) * 110.0
        score += self._center_penalty(candidate.x, candidate.y) * 0.18
        clearance = (self.occupancy.clearance(occupancy, box) if occupancy is not None else self._clearance_bonus(box, visual_regions))
        score -= clearance * 1.10

        if cue.priority >= 85 and self._zone_family(candidate.zone) in {"top", "bottom"}:
            score -= 0.045

        return score, candidate, box, actual_overlap

    def _visual_regions(
        self,
        beat: StoryBeat,
        visual: CompositionBeat | None,
        assets_by_id: dict[str, VisualAsset],
    ) -> list[_VisualRegion]:
        if visual is None:
            return []
        primary = set(beat.primary_asset_ids)
        support = set(beat.support_asset_ids)
        output: list[_VisualRegion] = []
        for item in visual.items:
            if item.asset_id in primary:
                weight = 1.65
                pad_x, pad_y = 0.030, 0.035
            elif item.asset_id in support:
                weight = 1.25
                pad_x, pad_y = 0.022, 0.027
            else:
                weight = 1.0
                pad_x, pad_y = 0.016, 0.020
            footprint = self.footprints.resolve(item, assets_by_id.get(item.asset_id))
            box = footprint.box
            output.append(
                _VisualRegion(
                    box=box,
                    protected_box=self._expand(box, pad_x, pad_y),
                    weight=weight,
                )
            )
        return output

    @staticmethod
    def _anchor(cue: TextCue, visual: CompositionBeat | None) -> LayoutItem | None:
        if visual is None or not cue.anchor_asset_id:
            return None
        return next((item for item in visual.items if item.asset_id == cue.anchor_asset_id), None)

    @staticmethod
    def _human_prior(x: float, y: float) -> float:
        thirds = ((0.17, 0.16), (0.50, 0.14), (0.83, 0.16), (0.17, 0.84), (0.50, 0.86), (0.83, 0.84))
        nearest = min(((x - tx) ** 2 + (y - ty) ** 2) ** 0.5 for tx, ty in thirds)
        return nearest * 0.18

    @staticmethod
    def _zone_for(x: float, y: float) -> str:
        if y <= 0.30:
            return "top"
        if y >= 0.70:
            return "bottom"
        return "left" if x < 0.5 else "right"

    @staticmethod
    def _zone_family(zone: str) -> str:
        if "top" in zone:
            return "top"
        if "bottom" in zone:
            return "bottom"
        if "left" in zone:
            return "left"
        if "right" in zone:
            return "right"
        return zone

    @staticmethod
    def _center_penalty(x: float, y: float) -> float:
        dx = max(0.0, 0.22 - abs(x - 0.5))
        dy = max(0.0, 0.18 - abs(y - 0.5))
        return dx * dy

    @staticmethod
    def _clearance_bonus(box: Box, regions: list[_VisualRegion]) -> float:
        if not regions:
            return 0.20
        return min(TextPlacementDirector._box_distance(box, region.protected_box) for region in regions)

    def _edge_penalty(self, box: Box) -> float:
        left = max(0.0, self._SAFE_MARGIN_X - box[0])
        right = max(0.0, box[2] - (1.0 - self._SAFE_MARGIN_X))
        top = max(0.0, self._SAFE_MARGIN_Y - box[1])
        bottom = max(0.0, box[3] - (1.0 - self._SAFE_MARGIN_Y))
        return left + right + top + bottom

    @staticmethod
    def _visual_box(item: LayoutItem) -> Box:
        return TextPlacementDirector._box(item.x, item.y, item.width, item.height)

    @staticmethod
    def _box(x: float, y: float, width: float, height: float) -> Box:
        return (x - width / 2, y - height / 2, x + width / 2, y + height / 2)

    @staticmethod
    def _expand(box: Box, x_pad: float, y_pad: float) -> Box:
        return (
            max(0.0, box[0] - x_pad),
            max(0.0, box[1] - y_pad),
            min(1.0, box[2] + x_pad),
            min(1.0, box[3] + y_pad),
        )

    @staticmethod
    def _intersection_ratio(left: Box, right: Box) -> float:
        x0 = max(left[0], right[0])
        y0 = max(left[1], right[1])
        x1 = min(left[2], right[2])
        y1 = min(left[3], right[3])
        if x1 <= x0 or y1 <= y0:
            return 0.0
        overlap = (x1 - x0) * (y1 - y0)
        area = max(1e-6, (left[2] - left[0]) * (left[3] - left[1]))
        return overlap / area

    @staticmethod
    def _box_distance(left: Box, right: Box) -> float:
        dx = max(right[0] - left[2], left[0] - right[2], 0.0)
        dy = max(right[1] - left[3], left[1] - right[3], 0.0)
        return (dx * dx + dy * dy) ** 0.5

    @staticmethod
    def _center_distance(x0: float, y0: float, x1: float, y1: float) -> float:
        dx = x0 - x1
        dy = y0 - y1
        return (dx * dx + dy * dy) ** 0.5
