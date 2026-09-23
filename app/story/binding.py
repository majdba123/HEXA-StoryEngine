from __future__ import annotations

from dataclasses import dataclass

from app.models import SceneSource, StoryBeat, VisualAsset


@dataclass(frozen=True, slots=True)
class AssetBinding:
    """Semantic roles assigned to already-extracted visual assets.

    Binding does not alter layout. It tells Choreography which extracted object is the
    focal object, which object it can interact with, which assets behave as actors, and
    how Final Package semantic unit IDs map onto available cutouts. Mapping is best-effort
    and confidence is explicit; Choreography never fabricates an unavailable cutout.
    """

    focus_asset_id: str | None
    interaction_asset_id: str | None
    actor_asset_ids: tuple[str, ...] = ()
    semantic_asset_map: tuple[tuple[str, str], ...] = ()
    binding_confidence: float = 1.0


class SemanticAssetBinder:
    """Bind Final Package semantic units to existing cutouts conservatively.

    The package is the semantic authority. Extracted connected components often lack a
    one-to-one unit identifier, so this binder uses explicit asset roles first, declared
    character types second, and source geometry only as a bounded fallback. It never
    hard-codes scene numbers or business-domain nouns.
    """

    _CHARACTER_ROLE_WORDS = ("character", "narrator", "person", "human", "customer", "actor")

    def bind(
        self,
        *,
        scene: SceneSource | None,
        assets: list[VisualAsset],
        action: str,
        beat: StoryBeat | None = None,
    ) -> AssetBinding:
        del action  # semantics are read from the scene/Story context instead of action names.
        if not assets:
            return AssetBinding(None, None, (), (), 0.0)

        character_units = self._character_units(scene)
        character_count = min(2, len(character_units))
        actor_ids: tuple[str, ...] = ()
        if character_count:
            ranked = sorted(assets, key=self._character_score, reverse=True)
            candidates = [asset for asset in ranked if self._is_character_candidate(asset)]
            actor_ids = tuple(asset.id for asset in candidates[:character_count])

        authored_actor_ids = self._authored_character_assets(beat, assets)
        actor_ids = tuple(dict.fromkeys((*authored_actor_ids, *actor_ids)))
        actor_set = set(actor_ids)
        independent = [asset for asset in assets if asset.can_animate_independently]
        focus_pool = [asset for asset in independent if asset.id not in actor_set]
        if not focus_pool:
            focus_pool = independent or list(assets)
        focus_pool.sort(key=self._visual_weight, reverse=True)

        authored_focus = self._authored_focus_asset(beat, assets)
        focus = authored_focus or focus_pool[0]

        interaction_pool = [asset for asset in focus_pool[1:] if self._meaningful_support(asset, focus)]
        if interaction_pool:
            interaction = interaction_pool[0]
        else:
            actor_assets = [asset for asset in assets if asset.id in actor_set]
            actor_assets.sort(key=self._visual_weight, reverse=True)
            interaction = actor_assets[0] if actor_assets else None

        semantic_map = self._semantic_map(
            scene=scene,
            beat=beat,
            assets=assets,
            focus=focus,
            interaction=interaction,
            actor_ids=actor_ids,
        )
        confidence = self._binding_confidence(scene, semantic_map, assets)
        return AssetBinding(
            focus_asset_id=focus.id,
            interaction_asset_id=interaction.id if interaction is not None else None,
            actor_asset_ids=actor_ids,
            semantic_asset_map=tuple(semantic_map.items()),
            binding_confidence=confidence,
        )

    def _semantic_map(
        self,
        *,
        scene: SceneSource | None,
        beat: StoryBeat | None,
        assets: list[VisualAsset],
        focus: VisualAsset,
        interaction: VisualAsset | None,
        actor_ids: tuple[str, ...],
    ) -> dict[str, str]:
        if scene is None:
            return {}
        units = [unit for unit in scene.units if isinstance(unit, dict) and unit.get("unit_id")]
        if not units:
            return {}

        asset_by_id = {asset.id: asset for asset in assets}
        mapping: dict[str, str] = {}
        used: set[str] = set()

        # Story's locator-proven semantic activations are the strongest semantic->real
        # identity evidence available to Choreography. Reuse them before any geometry
        # heuristic so Final Package relationships cannot be rebound to the wrong cutout.
        if beat is not None:
            for activation in beat.asset_activations:
                unit_id = activation.semantic_unit_id
                asset_id = activation.asset_id
                if (
                    unit_id
                    and unit_id not in mapping
                    and asset_id in asset_by_id
                    and asset_id not in used
                ):
                    mapping[unit_id] = asset_id
                    used.add(asset_id)

        # Authored unit identity outranks area/role heuristics. Never derive meaning
        # from image filenames or silently swap an explicitly bound asset.
        for unit in units:
            unit_id = str(unit["unit_id"])
            declared = str(unit.get("asset_id") or unit_id)
            if declared in asset_by_id and declared not in used:
                mapping[unit_id] = declared
                used.add(declared)

        # Declared character units are the most reliable semantic->asset class mapping.
        for unit, asset_id in zip(self._character_units(scene), actor_ids):
            if str(unit["unit_id"]) in mapping or asset_id in used:
                continue
            mapping[str(unit["unit_id"])] = asset_id
            used.add(asset_id)

        target_order = list(beat.semantic_targets) if beat else []
        target_rank = {unit_id: index for index, unit_id in enumerate(target_order)}
        non_character = [unit for unit in units if not self._is_character_unit(unit)]
        non_character.sort(
            key=lambda unit: (
                0 if str(unit.get("role") or "").upper() == "PRIMARY" else 1,
                target_rank.get(str(unit.get("unit_id")), 10_000),
                str(unit.get("unit_id")),
            )
        )

        candidates = [focus]
        if interaction is not None and interaction.id != focus.id:
            candidates.append(interaction)
        candidates.extend(
            sorted(
                (asset for asset in assets if asset.id not in actor_ids and asset.id not in {row.id for row in candidates}),
                key=self._visual_weight,
                reverse=True,
            )
        )
        for unit in non_character:
            unit_id = str(unit["unit_id"])
            if unit_id in mapping:
                continue
            candidate = next((asset for asset in candidates if asset.id not in used), None)
            if candidate is None:
                break
            mapping[unit_id] = candidate.id
            used.add(candidate.id)

        # If a semantic relationship points to a declared character but geometry could
        # not identify the actor, do not fake the mapping. Leaving it unresolved lets
        # InteractionIntent become non-executable while preserving the semantic evidence.
        return {unit_id: asset_id for unit_id, asset_id in mapping.items() if asset_id in asset_by_id}

    @staticmethod
    def _authored_character_assets(
        beat: StoryBeat | None,
        assets: list[VisualAsset],
    ) -> tuple[str, ...]:
        """Resolve semantic CHARACTER/ACTOR roles through Story-proven identity.

        Final Package 1.1 often represents units as VISUAL_ASSET_INTENT, so scene-unit
        type alone cannot identify people. Story activations already map semantic units
        to real cutouts; reuse that evidence so a large character does not become focus
        merely because it occupies more pixels than the actual concept.
        """
        if beat is None or beat.semantic_context is None:
            return ()
        valid_assets = {asset.id for asset in assets}
        actor_units = {
            entity.unit_id
            for entity in beat.semantic_context.entities
            if str(entity.role or "").upper() in {"CHARACTER", "ACTOR"}
            or str(entity.entity_type or "").upper()
            in {"MAIN_CHARACTER", "SECONDARY_CHARACTER", "CHARACTER", "PERSON"}
        }
        if not actor_units:
            return ()
        return tuple(dict.fromkeys(
            row.asset_id
            for row in beat.asset_activations
            if row.semantic_unit_id in actor_units and row.asset_id in valid_assets
        ))

    @staticmethod
    def _authored_focus_asset(
        beat: StoryBeat | None,
        assets: list[VisualAsset],
    ) -> VisualAsset | None:
        if beat is None:
            return None
        by_id = {asset.id: asset for asset in assets}
        rank = {
            "PRIMARY": 0,
            "RESULT": 1,
            "CONTEXT": 2,
            "SUPPORT": 3,
        }
        candidates = [
            (
                rank.get(str(row.visual_focus or "").upper(), 99),
                row.sequence_order if row.sequence_order is not None else 10_000,
                row.asset_id,
            )
            for row in beat.asset_activations
            if row.visual_focus and row.asset_id in by_id
        ]
        if not candidates:
            return None
        _, _, asset_id = min(candidates)
        return by_id[asset_id]

    @staticmethod
    def _binding_confidence(
        scene: SceneSource | None,
        semantic_map: dict[str, str],
        assets: list[VisualAsset],
    ) -> float:
        if scene is None or not scene.units:
            return 0.70 if assets else 0.0
        declared = [unit for unit in scene.units if isinstance(unit, dict) and unit.get("unit_id")]
        if not declared:
            return 0.72
        coverage = len(semantic_map) / len(declared)
        return max(0.45, min(1.0, 0.58 + coverage * 0.42))

    @staticmethod
    def _character_units(scene: SceneSource | None) -> list[dict]:
        if scene is None:
            return []
        return [unit for unit in scene.units if SemanticAssetBinder._is_character_unit(unit)]

    @staticmethod
    def _is_character_unit(unit: dict) -> bool:
        unit_type = str(unit.get("type") or "").upper()
        return unit_type in {"MAIN_CHARACTER", "SECONDARY_CHARACTER", "CHARACTER", "PERSON"}

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
