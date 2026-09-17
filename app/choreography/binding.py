from __future__ import annotations

from dataclasses import dataclass

from app.models import SceneSource, VisualAsset


@dataclass(frozen=True, slots=True)
class AssetBinding:
    """Semantic roles assigned to already-extracted visual assets.

    Binding does not alter layout. It only tells Choreography which extracted object is
    the focal object for the current event, which object it should interact with, and
    which assets behave as human actors/reaction witnesses.
    """

    focus_asset_id: str | None
    interaction_asset_id: str | None
    actor_asset_ids: tuple[str, ...] = ()


class SemanticAssetBinder:
    """Bind package semantics to cutouts using metadata + conservative geometry.

    The Final Package describes *what* is a main/secondary character but extracted
    connected components do not always carry that semantic label. This binder therefore
    uses explicit asset roles when available and only falls back to conservative portrait
    geometry when the scene metadata says a character is present. It never performs
    topic- or scene-id-specific matching.
    """

    _CHARACTER_ROLE_WORDS = ("character", "narrator", "person", "human", "customer")

    def bind(
        self,
        *,
        scene: SceneSource | None,
        assets: list[VisualAsset],
        action: str,
    ) -> AssetBinding:
        del action  # reserved for future action-specific target policies
        if not assets:
            return AssetBinding(None, None, ())

        character_count = self._declared_character_count(scene)
        actor_ids: tuple[str, ...] = ()
        if character_count:
            ranked = sorted(
                assets,
                key=lambda asset: self._character_score(asset),
                reverse=True,
            )
            candidates = [asset for asset in ranked if self._is_character_candidate(asset)]
            actor_ids = tuple(asset.id for asset in candidates[:character_count])

        actor_set = set(actor_ids)
        independent = [asset for asset in assets if asset.can_animate_independently]
        focus_pool = [asset for asset in independent if asset.id not in actor_set]
        if not focus_pool:
            focus_pool = independent or list(assets)

        # Prefer the largest meaningful non-character object. Tiny labels/arrows are
        # supporting evidence and should not steal the event from the main concept.
        focus_pool.sort(key=self._visual_weight, reverse=True)
        focus = focus_pool[0]

        interaction_pool = [asset for asset in focus_pool[1:] if self._meaningful_support(asset, focus)]
        if interaction_pool:
            interaction = interaction_pool[0]
        else:
            actor_assets = [asset for asset in assets if asset.id in actor_set]
            actor_assets.sort(key=self._visual_weight, reverse=True)
            interaction = actor_assets[0] if actor_assets else None

        return AssetBinding(
            focus_asset_id=focus.id,
            interaction_asset_id=interaction.id if interaction is not None else None,
            actor_asset_ids=actor_ids,
        )

    @staticmethod
    def _declared_character_count(scene: SceneSource | None) -> int:
        if scene is None:
            return 0
        count = 0
        for unit in scene.units:
            unit_type = str(unit.get("type") or "").upper()
            semantic_name = str(unit.get("semantic_name") or "").casefold()
            if unit_type in {"MAIN_CHARACTER", "SECONDARY_CHARACTER"}:
                count += 1
            elif "character" in semantic_name or "customer" in semantic_name:
                count += 1
        return min(2, count)

    @classmethod
    def _is_character_candidate(cls, asset: VisualAsset) -> bool:
        role = (asset.role or "").casefold()
        if any(word in role for word in cls._CHARACTER_ROLE_WORDS):
            return True
        geometry = cls._normalized_geometry(asset)
        if geometry is None:
            return False
        width, height, _cx = geometry
        if asset.source_bbox:
            _x, _y, raw_width, raw_height = asset.source_bbox
            portrait = raw_height / max(raw_width, 1)
        else:
            portrait = height / max(width, 1e-6)
        area = width * height
        # Deliberately strict: only use geometry when scene metadata already says a
        # character exists. This avoids classifying phones/towers as people globally.
        return (
            height >= 0.52
            and 0.16 <= width <= 0.42
            and portrait >= 1.16
            and 0.055 <= area <= 0.38
        )

    @classmethod
    def _character_score(cls, asset: VisualAsset) -> float:
        role = (asset.role or "").casefold()
        role_bonus = 3.0 if any(word in role for word in cls._CHARACTER_ROLE_WORDS) else 0.0
        geometry = cls._normalized_geometry(asset)
        if geometry is None:
            return role_bonus + (asset.source_area_ratio or 0.0)
        width, height, center_x = geometry
        if asset.source_bbox:
            _x, _y, raw_width, raw_height = asset.source_bbox
            portrait = min(2.2, raw_height / max(raw_width, 1))
        else:
            portrait = min(2.2, height / max(width, 1e-6))
        edge_bonus = max(0.0, abs(center_x - 0.5) - 0.16) * 1.8
        return role_bonus + height * 2.0 + portrait * 0.75 + edge_bonus - max(0.0, width - 0.42) * 4.0

    @staticmethod
    def _visual_weight(asset: VisualAsset) -> float:
        area = asset.source_area_ratio
        if area is not None:
            return float(area)
        if asset.source_bbox and asset.source_canvas_width and asset.source_canvas_height:
            _x, _y, width, height = asset.source_bbox
            return (width * height) / (asset.source_canvas_width * asset.source_canvas_height)
        return 0.0

    @classmethod
    def _meaningful_support(cls, asset: VisualAsset, focus: VisualAsset) -> bool:
        focus_weight = max(cls._visual_weight(focus), 1e-6)
        weight = cls._visual_weight(asset)
        # Ignore microscopic detached labels/arrows as the main interaction target,
        # while still allowing a clearly independent second object to participate.
        return weight >= max(0.012, focus_weight * 0.12)

    @staticmethod
    def _normalized_geometry(asset: VisualAsset) -> tuple[float, float, float] | None:
        if not asset.source_bbox or not asset.source_canvas_width or not asset.source_canvas_height:
            return None
        x, _y, width, height = asset.source_bbox
        canvas_w = max(1, asset.source_canvas_width)
        canvas_h = max(1, asset.source_canvas_height)
        return (
            width / canvas_w,
            height / canvas_h,
            (x + width / 2) / canvas_w,
        )
