from __future__ import annotations

from collections import defaultdict

from app.models import (
    CompositionBeat,
    LayoutItem,
    StoryBeat,
    TextCompositionBeat,
    TextCue,
    TextLayoutItem,
)


class TextCompositionPlanner:
    """Place sparse text independently with collision-aware semantic anchoring.

    Visual composition remains sourced from Final Package geometry. Text has no source
    bbox, so it evaluates a deterministic candidate field around its semantic anchor and
    selects the lowest-cost safe placement. Large overlap penalties keep typography off
    the authored artwork while proximity penalties preserve the story relationship.
    """

    def plan(
        self,
        beats: list[StoryBeat],
        visual_composition: list[CompositionBeat],
        text_cues: list[TextCue],
    ) -> list[TextCompositionBeat]:
        visual_by_beat = {beat.beat_id: beat for beat in visual_composition}
        cues_by_beat: dict[str, list[TextCue]] = defaultdict(list)
        for cue in text_cues:
            cues_by_beat[cue.beat_id].append(cue)

        output: list[TextCompositionBeat] = []
        for beat in beats:
            cues = sorted(
                cues_by_beat.get(beat.id, []),
                key=lambda cue: (cue.spoken_start, -cue.priority, cue.id),
            )
            if not cues:
                continue
            visual = visual_by_beat.get(beat.id)
            occupied: list[tuple[float, float, float, float]] = []
            items: list[TextLayoutItem] = []
            for cue in cues:
                item, box = self._layout_item(cue, visual, occupied)
                items.append(item)
                occupied.append(box)
            output.append(TextCompositionBeat(beat_id=beat.id, items=items))
        return output

    def _layout_item(
        self,
        cue: TextCue,
        visual: CompositionBeat | None,
        occupied_text: list[tuple[float, float, float, float]],
    ) -> tuple[TextLayoutItem, tuple[float, float, float, float]]:
        anchor = self._anchor(cue, visual)
        width, height = self._estimated_box(cue)
        candidates = self._candidates(anchor, width, height)
        visual_boxes = [self._visual_box(item) for item in (visual.items if visual else [])]

        best = min(
            candidates,
            key=lambda row: self._placement_cost(
                row[0], row[1], width, height,
                visual_boxes=visual_boxes,
                occupied_text=occupied_text,
                anchor=anchor,
                preference=row[3],
            ),
        )
        x, y, placement, _ = best
        box = self._box(x, y, width, height)
        return TextLayoutItem(
            text_cue_id=cue.id,
            x=x,
            y=y,
            max_width=width,
            z=50 + min(20, cue.priority // 5),
            anchor_asset_id=cue.anchor_asset_id,
            placement=placement,
        ), box

    @staticmethod
    def _anchor(cue: TextCue, visual: CompositionBeat | None) -> LayoutItem | None:
        if visual is None or not cue.anchor_asset_id:
            return None
        return next((item for item in visual.items if item.asset_id == cue.anchor_asset_id), None)

    @staticmethod
    def _estimated_box(cue: TextCue) -> tuple[float, float]:
        # Conservative box for the larger production typography. Real shaping is done
        # by libass; this estimate is solely for collision scoring.
        base = 0.22 + min(0.34, len(cue.text) * 0.015)
        if cue.priority >= 85:
            base += 0.05
        return min(0.60, base), 0.155 if cue.priority >= 85 else 0.135

    def _candidates(
        self,
        anchor: LayoutItem | None,
        width: float,
        height: float,
    ) -> list[tuple[float, float, str, float]]:
        safe = [
            (0.50, 0.12, "safe_top", 0.20),
            (0.50, 0.88, "safe_bottom", 0.26),
            (0.23, 0.16, "safe_top_left", 0.30),
            (0.77, 0.16, "safe_top_right", 0.30),
            (0.23, 0.84, "safe_bottom_left", 0.34),
            (0.77, 0.84, "safe_bottom_right", 0.34),
        ]
        if anchor is None:
            return safe

        vertical_gap = anchor.height / 2 + height / 2 + 0.050
        horizontal_gap = anchor.width / 2 + width / 2 + 0.050
        diagonal_x = anchor.width / 2 + width * 0.34 + 0.035
        diagonal_y = anchor.height / 2 + height * 0.34 + 0.035
        local = [
            (self._clamp(anchor.x, 0.14, 0.86), self._clamp(anchor.y - vertical_gap, 0.10, 0.90), "above_anchor", 0.00),
            (self._clamp(anchor.x, 0.14, 0.86), self._clamp(anchor.y + vertical_gap, 0.10, 0.90), "below_anchor", 0.06),
            (self._clamp(anchor.x - horizontal_gap, 0.13, 0.87), self._clamp(anchor.y, 0.12, 0.88), "left_of_anchor", 0.10),
            (self._clamp(anchor.x + horizontal_gap, 0.13, 0.87), self._clamp(anchor.y, 0.12, 0.88), "right_of_anchor", 0.10),
            (self._clamp(anchor.x - diagonal_x, 0.13, 0.87), self._clamp(anchor.y - diagonal_y, 0.11, 0.89), "above_left", 0.12),
            (self._clamp(anchor.x + diagonal_x, 0.13, 0.87), self._clamp(anchor.y - diagonal_y, 0.11, 0.89), "above_right", 0.12),
            (self._clamp(anchor.x - diagonal_x, 0.13, 0.87), self._clamp(anchor.y + diagonal_y, 0.11, 0.89), "below_left", 0.16),
            (self._clamp(anchor.x + diagonal_x, 0.13, 0.87), self._clamp(anchor.y + diagonal_y, 0.11, 0.89), "below_right", 0.16),
        ]
        return [*local, *safe]

    def _placement_cost(
        self,
        x: float,
        y: float,
        width: float,
        height: float,
        *,
        visual_boxes: list[tuple[float, float, float, float]],
        occupied_text: list[tuple[float, float, float, float]],
        anchor: LayoutItem | None,
        preference: float,
    ) -> float:
        box = self._box(x, y, width, height)
        cost = preference
        # A text/artwork collision is visually much worse than being slightly farther
        # from the anchor. Text/text collision is even more expensive.
        cost += sum(self._intersection_ratio(box, other) * 18.0 for other in visual_boxes)
        cost += sum(self._intersection_ratio(box, other) * 32.0 for other in occupied_text)
        if anchor is not None:
            dx = x - anchor.x
            dy = y - anchor.y
            cost += ((dx * dx + dy * dy) ** 0.5) * 0.42
        x0, y0, x1, y1 = box
        margin_penalty = max(0.0, 0.045 - x0) + max(0.0, x1 - 0.955)
        margin_penalty += max(0.0, 0.055 - y0) + max(0.0, y1 - 0.945)
        return cost + margin_penalty * 36.0

    @staticmethod
    def _visual_box(item: LayoutItem) -> tuple[float, float, float, float]:
        return TextCompositionPlanner._box(item.x, item.y, item.width, item.height)

    @staticmethod
    def _box(x: float, y: float, width: float, height: float) -> tuple[float, float, float, float]:
        return (x - width / 2, y - height / 2, x + width / 2, y + height / 2)

    @staticmethod
    def _intersection_ratio(
        left: tuple[float, float, float, float],
        right: tuple[float, float, float, float],
    ) -> float:
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
    def _clamp(value: float, low: float, high: float) -> float:
        return max(low, min(high, value))
