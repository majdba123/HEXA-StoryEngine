from __future__ import annotations

from dataclasses import dataclass
from math import hypot, inf

from app.models import AssetActivation, LayoutItem, StoryBeat, VisualAsset


_MULTI_IDENTITY_EVIDENCE = "visual_identity_multi_cutout_member"


@dataclass(frozen=True, slots=True)
class MotionOrderSlot:
    """One Composition item plus the authoritative order Motion must honor."""

    item: LayoutItem
    activation: AssetActivation | None
    original_index: int
    external_sequence_order: int | None
    internal_index: int = 0
    internal_count: int = 1
    order_source: str = "layout_order"

    @property
    def is_internal_visual_unit(self) -> bool:
        return self.internal_count > 1

    def to_payload(self) -> dict[str, object]:
        activation = self.activation
        return {
            "source": self.order_source,
            "semantic_group_id": activation.semantic_group_id if activation else None,
            "semantic_unit_id": activation.semantic_unit_id if activation else None,
            "sequence_order": self.external_sequence_order,
            "semantic_event_id": activation.semantic_event_id if activation else None,
            "semantic_event_order": activation.semantic_event_order if activation else None,
            "semantic_event_roles": list(activation.semantic_event_roles) if activation else [],
            "semantic_event_dependency_ids": (
                list(activation.semantic_event_dependency_ids) if activation else []
            ),
            "compound_visual_classification": (
                activation.compound_visual_classification if activation else None
            ),
            "internal_index": self.internal_index,
            "internal_count": self.internal_count,
        }


class MotionOrderResolver:
    """Resolve deterministic reveal order without changing Composition geometry.

    Final Package sequence_order is authoritative whenever Story has preserved it in
    an AssetActivation. Layout/extraction order is only a fallback.

    When one semantic intent maps to several real cutouts, Motion derives a deterministic
    internal order from authored geometry while keeping every member inside the
    Story-owned semantic window. No topic names, scene IDs, or asset-count rules are used.
    """

    _EPSILON = 1e-9
    _PROJECTION_TIE = 0.012
    _SIZE_VARIATION_RATIO = 1.12

    def resolve(
        self,
        *,
        beat: StoryBeat,
        items: list[LayoutItem],
        assets_by_id: dict[str, VisualAsset] | None = None,
    ) -> list[MotionOrderSlot]:
        activation_by_asset = {row.asset_id: row for row in beat.asset_activations}
        assets = assets_by_id or {}
        slots = [
            MotionOrderSlot(
                item=item,
                activation=activation_by_asset.get(item.asset_id),
                original_index=index,
                external_sequence_order=(
                    activation_by_asset[item.asset_id].sequence_order
                    if item.asset_id in activation_by_asset
                    else None
                ),
                order_source=(
                    "final_package_sequence_order"
                    if self._has_authoritative_sequence(
                        activation_by_asset.get(item.asset_id)
                    )
                    else "layout_order"
                ),
            )
            for index, item in enumerate(items)
        ]

        internal_rank: dict[str, tuple[int, int, str]] = {}
        for members in self._multi_cutout_groups(slots, assets).values():
            ordered = self._order_visual_unit(members, slots, assets)
            count = len(ordered)
            for index, slot in enumerate(ordered):
                internal_rank[slot.item.asset_id] = (
                    index,
                    count,
                    "visual_locator_multi_geometry_flow",
                )

        enriched: list[MotionOrderSlot] = []
        for slot in slots:
            rank = internal_rank.get(slot.item.asset_id)
            if rank is None:
                enriched.append(slot)
                continue
            internal_index, internal_count, source = rank
            enriched.append(
                MotionOrderSlot(
                    item=slot.item,
                    activation=slot.activation,
                    original_index=slot.original_index,
                    external_sequence_order=slot.external_sequence_order,
                    internal_index=internal_index,
                    internal_count=internal_count,
                    order_source=(
                        f"{slot.order_source}+{source}"
                        if slot.order_source != "layout_order"
                        else source
                    ),
                )
            )

        return sorted(enriched, key=self._sort_key)

    @staticmethod
    def _has_authoritative_sequence(
        activation: AssetActivation | None,
    ) -> bool:
        return bool(
            activation is not None
            and activation.semantic_group_id
            and activation.sequence_order is not None
            and activation.source == "final_package_semantic_binding"
        )

    @classmethod
    def _sort_key(cls, slot: MotionOrderSlot) -> tuple[object, ...]:
        activation = slot.activation
        if cls._has_authoritative_sequence(activation):
            assert activation is not None
            return (
                0,
                activation.spoken_start
                if activation.spoken_start is not None
                else inf,
                activation.trigger_char_start
                if activation.trigger_char_start is not None
                else inf,
                activation.semantic_group_id or "",
                activation.semantic_event_order
                if activation.semantic_event_order is not None
                else 10_000,
                activation.sequence_order
                if activation.sequence_order is not None
                else 10_000,
                slot.internal_index,
                slot.original_index,
            )
        return (1, slot.original_index)

    @classmethod
    def _multi_cutout_groups(
        cls,
        slots: list[MotionOrderSlot],
        assets: dict[str, VisualAsset],
    ) -> dict[tuple[object, ...], list[MotionOrderSlot]]:
        groups: dict[tuple[object, ...], list[MotionOrderSlot]] = {}
        for slot in slots:
            activation = slot.activation
            if (
                activation is None
                or not activation.semantic_unit_id
                or not activation.semantic_group_id
                or activation.sequence_order is None
                or activation.group_animation_policy
                == "SIMULTANEOUS_VISUAL_UNIT"
                or activation.compound_visual_classification == "COMPOUND_REQUIRED"
                or activation.internal_progression_unavailable
                or _MULTI_IDENTITY_EVIDENCE not in activation.evidence
            ):
                continue
            key = (
                activation.semantic_group_id,
                activation.sequence_order,
                activation.semantic_unit_id,
                activation.trigger_char_start,
                activation.trigger_char_end,
            )
            groups.setdefault(key, []).append(slot)

        return {
            key: rows
            for key, rows in groups.items()
            if len(rows) > 1 and not cls._shares_locked_family(rows, assets)
        }

    @staticmethod
    def _shares_locked_family(
        rows: list[MotionOrderSlot],
        assets: dict[str, VisualAsset],
    ) -> bool:
        """Keep Pass2 family canvases simultaneous; never expose reconstruction holes."""

        families: dict[str, int] = {}
        for row in rows:
            asset = assets.get(row.item.asset_id)
            if (
                asset is None
                or not asset.render_as_family_canvas
                or not asset.asset_family_id
            ):
                continue
            families[asset.asset_family_id] = (
                families.get(asset.asset_family_id, 0) + 1
            )
        return any(count > 1 for count in families.values())

    def _order_visual_unit(
        self,
        members: list[MotionOrderSlot],
        all_slots: list[MotionOrderSlot],
        assets: dict[str, VisualAsset],
    ) -> list[MotionOrderSlot]:
        sample = members[0].activation
        assert sample is not None
        group_id = sample.semantic_group_id
        sequence_order = sample.sequence_order
        assert group_id is not None and sequence_order is not None

        group_centroid = self._centroid([slot.item for slot in members])
        previous = self._neighbor_centroid(
            all_slots,
            group_id=group_id,
            sequence_order=sequence_order,
            before=True,
        )
        following = self._neighbor_centroid(
            all_slots,
            group_id=group_id,
            sequence_order=sequence_order,
            before=False,
        )

        if previous is not None and following is not None:
            direction = (
                following[0] - previous[0],
                following[1] - previous[1],
            )
        elif following is not None:
            direction = (
                following[0] - group_centroid[0],
                following[1] - group_centroid[1],
            )
        elif previous is not None:
            direction = (
                group_centroid[0] - previous[0],
                group_centroid[1] - previous[1],
            )
        else:
            direction = self._dominant_axis([slot.item for slot in members])

        magnitude = hypot(*direction)
        if magnitude <= self._EPSILON:
            direction = self._dominant_axis([slot.item for slot in members])
            magnitude = max(self._EPSILON, hypot(*direction))
        unit = (direction[0] / magnitude, direction[1] / magnitude)

        projections = {
            slot.item.asset_id: slot.item.x * unit[0] + slot.item.y * unit[1]
            for slot in members
        }
        spread = max(projections.values()) - min(projections.values())
        areas = {
            slot.item.asset_id: self._visual_area(
                slot.item,
                assets.get(slot.item.asset_id),
            )
            for slot in members
        }
        positive = [value for value in areas.values() if value > self._EPSILON]
        area_ratio = (
            max(positive) / min(positive) if len(positive) >= 2 else 1.0
        )

        if (
            spread <= self._PROJECTION_TIE
            and area_ratio >= self._SIZE_VARIATION_RATIO
        ):
            return sorted(
                members,
                key=lambda slot: (
                    areas[slot.item.asset_id],
                    slot.item.x,
                    slot.item.y,
                    slot.original_index,
                ),
            )

        return sorted(
            members,
            key=lambda slot: (
                projections[slot.item.asset_id],
                areas[slot.item.asset_id],
                slot.original_index,
            ),
        )

    @staticmethod
    def _visual_area(
        item: LayoutItem,
        asset: VisualAsset | None,
    ) -> float:
        area = max(0.0, item.width) * max(0.0, item.height)
        if area > 0.0:
            return area
        if asset is not None and asset.source_area_ratio is not None:
            return float(asset.source_area_ratio)
        return 0.0

    @staticmethod
    def _centroid(items: list[LayoutItem]) -> tuple[float, float]:
        if not items:
            return (0.5, 0.5)
        return (
            sum(item.x for item in items) / len(items),
            sum(item.y for item in items) / len(items),
        )

    @classmethod
    def _neighbor_centroid(
        cls,
        slots: list[MotionOrderSlot],
        *,
        group_id: str,
        sequence_order: int,
        before: bool,
    ) -> tuple[float, float] | None:
        candidates: dict[int, list[LayoutItem]] = {}
        for slot in slots:
            activation = slot.activation
            if (
                activation is None
                or activation.semantic_group_id != group_id
                or activation.sequence_order is None
                or activation.sequence_order == sequence_order
            ):
                continue
            if before and activation.sequence_order >= sequence_order:
                continue
            if not before and activation.sequence_order <= sequence_order:
                continue
            candidates.setdefault(
                activation.sequence_order,
                [],
            ).append(slot.item)
        if not candidates:
            return None
        order = max(candidates) if before else min(candidates)
        return cls._centroid(candidates[order])

    @staticmethod
    def _dominant_axis(items: list[LayoutItem]) -> tuple[float, float]:
        if not items:
            return (1.0, 0.0)
        xs = [item.x for item in items]
        ys = [item.y for item in items]
        if max(xs) - min(xs) >= max(ys) - min(ys):
            return (1.0, 0.0)
        return (0.0, 1.0)
