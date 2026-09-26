from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.shared.errors import InvalidPackageError

from .authority import (
    resolve_semantic_collection,
    resolve_semantic_mapping,
    resolve_semantic_record,
)
from .enums import (
    AnchorGranularity,
    BindingType,
    CompoundVisualClassification,
    ContinuityMode,
    SemanticGroupAnimationPolicy,
    VisualFocus,
)
from .models import (
    CanonicalAsset,
    CanonicalContinuity,
    CanonicalManifestAsset,
    CanonicalManifestObject,
    CanonicalPackage,
    CanonicalProgression,
    CanonicalRelation,
    CanonicalScene,
    CanonicalScriptSpan,
    CanonicalSemanticEvent,
    CanonicalSemanticGroup,
    CanonicalVisualLocator,
    CanonicalVisualProgression,
)


class CanonicalNormalizer:
    """Normalize a validated raw Final Package into one typed runtime contract."""

    def normalize(self, package: Any) -> CanonicalPackage:
        if isinstance(package, CanonicalPackage):
            return package
        manifest = self._mapping(getattr(package, "manifest", None))
        scene_plan = self._mapping(getattr(package, "scene_plan", None))
        bindings = self._mapping(getattr(package, "semantic_bindings", None))

        plan_scenes = self._indexed(scene_plan.get("scenes"), "scene_id", "id")
        binding_scenes = self._indexed(bindings.get("scenes"), "scene_id")
        canonical_scenes: list[CanonicalScene] = []

        for legacy_scene in getattr(package, "scenes", ()):  # already structurally validated
            scene_id = str(legacy_scene.id)
            plan = plan_scenes.get(scene_id, {})
            binding = binding_scenes.get(scene_id, {})
            canonical_scenes.append(
                self._scene(legacy_scene=legacy_scene, plan=plan, binding=binding)
            )

        return CanonicalPackage(
            root=package.root,
            package_id=str(package.package_id),
            script=getattr(package, "script", None),
            schema_name=self._string(manifest.get("package_schema")),
            schema_version=self._string(manifest.get("package_version")),
            scenes=tuple(canonical_scenes),
            manifest_objects=tuple(self._manifest_objects(manifest.get("objects"))),
            manifest_assets=tuple(self._manifest_assets(manifest.get("assets"))),
            semantic_binding_schema_name=self._string(bindings.get("schema_name")),
            semantic_binding_schema_version=self._string(bindings.get("schema_version")),
            semantic_bindings_present=bool(bindings),
            extension_metadata=self._extras(
                manifest,
                {
                    "package_schema", "package_version", "objects", "assets", "scenes",
                    "scene_plan", "semantic_bindings", "canonical_script", "script",
                },
            ),
        )

    def _scene(self, *, legacy_scene: Any, plan: Mapping[str, Any], binding: Mapping[str, Any]) -> CanonicalScene:
        if not plan:
            plan = {
                "purpose": getattr(legacy_scene, "purpose", None),
                "visual_concept": getattr(legacy_scene, "visual_concept", None),
                "relation_to_previous": getattr(legacy_scene, "relation_to_previous", None),
                "units": list(getattr(legacy_scene, "units", ()) or ()),
                "visual_progression": list(getattr(legacy_scene, "visual_progression", ()) or ()),
                "semantic_events": list(getattr(legacy_scene, "semantic_events", ()) or ()),
                "progression": getattr(legacy_scene, "semantic_progression", None),
            }
        binding_assets = self._indexed(binding.get("assets"), "asset_id")
        plan_unit_rows = [
            row for row in (plan.get("units") or ()) if isinstance(row, Mapping)
        ]
        plan_units = self._indexed(plan_unit_rows, "asset_id", "unit_id")
        asset_ids = list(dict.fromkeys([*plan_units, *binding_assets]))
        assets_list = [
            self._asset(
                scene_id=str(legacy_scene.id),
                plan=self._mapping(plan_units.get(asset_id)),
                binding=self._mapping(binding_assets.get(asset_id)),
            )
            for asset_id in asset_ids
        ]
        for index, row in enumerate(plan_unit_rows, start=1):
            if row.get("asset_id") or row.get("unit_id"):
                continue
            fallback = dict(row)
            fallback_id = f"{legacy_scene.id}:legacy-unit-{index:03d}"
            fallback.setdefault("unit_id", fallback_id)
            fallback.setdefault("asset_id", fallback_id)
            fallback.setdefault("type", "LEGACY_UNIT")
            assets_list.append(
                self._asset(scene_id=str(legacy_scene.id), plan=fallback, binding={})
            )
        assets = tuple(assets_list)

        events_source = resolve_semantic_collection(
            plan.get("semantic_events"), binding.get("semantic_events")
        )
        relations_source = resolve_semantic_collection(
            plan.get("relations"), binding.get("relations")
        )
        progression_source = resolve_semantic_mapping(
            plan.get("progression"), binding.get("progression")
        )
        groups_source = binding.get("semantic_groups")

        visual_progression = tuple(
            self._visual_progression(row)
            for row in getattr(legacy_scene, "visual_progression", ())
            if isinstance(row, Mapping)
        )
        if not visual_progression:
            visual_progression = tuple(
                self._visual_progression(row)
                for row in plan.get("visual_progression", ()) or ()
                if isinstance(row, Mapping)
            )

        return CanonicalScene(
            id=str(legacy_scene.id),
            image_path=legacy_scene.image_path,
            order=int(legacy_scene.order),
            title=getattr(legacy_scene, "title", None),
            narration_hint=getattr(legacy_scene, "narration_hint", None),
            script_char_start=getattr(legacy_scene, "script_char_start", None),
            script_char_end=getattr(legacy_scene, "script_char_end", None),
            purpose=self._string(plan.get("purpose")) or getattr(legacy_scene, "purpose", None),
            visual_concept=self._string(plan.get("visual_concept")) or getattr(legacy_scene, "visual_concept", None),
            relation_to_previous=self._string(plan.get("relation_to_previous")) or getattr(legacy_scene, "relation_to_previous", None),
            character_category=self._string(binding.get("character_category")) or self._string(plan.get("character_category")),
            units=assets,
            visual_progression=visual_progression,
            semantic_events=tuple(
                self._event(row, scene_id=str(legacy_scene.id))
                for row in (events_source or ())
                if isinstance(row, Mapping)
            ),
            semantic_groups=tuple(
                self._group(row)
                for row in (groups_source or ())
                if isinstance(row, Mapping)
            ),
            relations=tuple(
                self._relation(row)
                for row in (relations_source or ())
                if isinstance(row, Mapping)
                and row.get("subject_asset_id")
                and row.get("object_asset_id")
                and (row.get("relation_type") or row.get("relationship"))
            ),
            semantic_progression=(
                self._progression(progression_source)
                if isinstance(progression_source, Mapping)
                else None
            ),
            extension_metadata={},
        )

    def _asset(self, *, scene_id: str, plan: Mapping[str, Any], binding: Mapping[str, Any]) -> CanonicalAsset:
        # Semantic bindings own semantic facts; scene-plan units are the structural fallback.
        merged = resolve_semantic_record(plan, binding)
        asset_id = self._string(merged.get("asset_id") or merged.get("unit_id"))
        if not asset_id:
            raise InvalidPackageError(f"canonical asset missing identity: {scene_id}")
        return CanonicalAsset(
            unit_id=self._string(merged.get("unit_id")) or asset_id,
            asset_id=asset_id,
            scene_id=scene_id,
            type=self._string(merged.get("type")) or "VISUAL_ASSET_INTENT",
            semantic_name=self._string(merged.get("semantic_name")),
            visual_concept=self._string(merged.get("visual_concept")),
            semantic_meaning=self._string(merged.get("semantic_meaning")),
            role=self._string(merged.get("role")),
            semantic_role=self._string(merged.get("semantic_role")),
            semantic_intent=self._string(merged.get("semantic_intent")),
            narrative_function=self._string(merged.get("narrative_function")),
            binding_type=self._enum(BindingType, merged.get("binding_type")),
            script_text=self._string(merged.get("script_text")),
            script_span=self._span(merged.get("script_span")),
            appear_trigger=self._span(merged.get("appear_trigger")),
            focus_trigger=self._span(merged.get("focus_trigger")),
            exit_trigger=self._span(merged.get("exit_trigger")),
            semantic_group_id=self._string(merged.get("semantic_group_id")),
            sequence_order=self._int(merged.get("sequence_order")),
            parent_asset_id=self._string(merged.get("parent_asset_id")),
            children_asset_ids=self._strings(merged.get("children_asset_ids")),
            confidence=self._float(merged.get("confidence"), 1.0),
            interaction_target=self._string(merged.get("interaction_target")),
            relationship=self._string(merged.get("relationship")),
            semantic_event_id=self._string(merged.get("semantic_event_id")),
            anchor_granularity=self._enum(AnchorGranularity, merged.get("anchor_granularity")),
            visual_focus=self._enum(VisualFocus, merged.get("visual_focus")),
            visual_state=(dict(merged["visual_state"]) if isinstance(merged.get("visual_state"), Mapping) else None),
            continuity=self._continuity(merged.get("continuity")),
            compound_visual_classification=self._enum(
                CompoundVisualClassification, merged.get("compound_visual_classification")
            ),
            internal_progression_unavailable=bool(merged.get("internal_progression_unavailable", False)),
            needs_review=bool(merged.get("needs_review", False)),
            ambiguity_reason=self._string(merged.get("ambiguity_reason")),
            visual_locator=self._locator(merged.get("visual_locator")),
            extension_metadata=self._extras(merged, CanonicalAsset.model_fields.keys()),
        )

    def _event(self, row: Mapping[str, Any], *, scene_id: str) -> CanonicalSemanticEvent:
        event_id = self._string(row.get("semantic_event_id"))
        if not event_id:
            raise InvalidPackageError(f"canonical semantic event missing id: {scene_id}")
        return CanonicalSemanticEvent(
            semantic_event_id=event_id,
            scene_id=self._string(row.get("scene_id")) or scene_id,
            script_text=self._string(row.get("script_text")),
            script_span=self._span(row.get("script_span")),
            anchor_granularity=self._enum(AnchorGranularity, row.get("anchor_granularity")),
            sequence_order=self._int(row.get("sequence_order")),
            visual_leader_asset_id=self._string(row.get("visual_leader_asset_id")),
            participant_asset_ids=self._strings(row.get("participant_asset_ids")),
            context_asset_ids=self._strings(row.get("context_asset_ids")),
            result_asset_ids=self._strings(row.get("result_asset_ids")),
            text_anchor_asset_id=self._string(row.get("text_anchor_asset_id")),
            confidence=self._float(row.get("confidence"), 1.0),
            needs_review=bool(row.get("needs_review", False)),
            ambiguity_reason=self._string(row.get("ambiguity_reason")),
            depends_on_event_ids=self._strings(row.get("depends_on_event_ids")),
            extension_metadata=self._extras(row, CanonicalSemanticEvent.model_fields.keys()),
        )

    def _relation(self, row: Mapping[str, Any]) -> CanonicalRelation:
        return CanonicalRelation(
            subject_asset_id=str(row["subject_asset_id"]),
            relation_type=str(row.get("relation_type") or row.get("relationship")),
            object_asset_id=str(row["object_asset_id"]),
            result_asset_id=self._string(row.get("result_asset_id")),
            script_text=self._string(row.get("script_text")),
            script_span=self._span(row.get("script_span")),
            confidence=self._float(row.get("confidence"), 1.0),
            extension_metadata=self._extras(row, CanonicalRelation.model_fields.keys()),
        )

    def _group(self, row: Mapping[str, Any]) -> CanonicalSemanticGroup:
        group_id = self._string(row.get("semantic_group_id"))
        if not group_id:
            raise InvalidPackageError("canonical semantic group missing id")
        policy = self._enum(
            SemanticGroupAnimationPolicy,
            row.get("animation_policy") or "SEQUENTIAL_WITHIN_PHRASE",
        )
        return CanonicalSemanticGroup(
            semantic_group_id=group_id,
            script_text=self._string(row.get("script_text")),
            animation_policy=policy or SemanticGroupAnimationPolicy.SEQUENTIAL_WITHIN_PHRASE,
            asset_ids=self._strings(row.get("asset_ids")),
            extension_metadata=self._extras(row, CanonicalSemanticGroup.model_fields.keys()),
        )

    def _progression(self, row: Mapping[str, Any]) -> CanonicalProgression:
        return CanonicalProgression(
            type=self._string(row.get("type")),
            event_order=self._strings(row.get("event_order")),
            extension_metadata=self._extras(row, CanonicalProgression.model_fields.keys()),
        )

    def _visual_progression(self, row: Mapping[str, Any]) -> CanonicalVisualProgression:
        return CanonicalVisualProgression(
            action=self._string(row.get("action")) or "EXPLAIN",
            targets=self._strings(row.get("targets")),
            trigger=self._span(row.get("trigger")),
            extension_metadata=self._extras(row, CanonicalVisualProgression.model_fields.keys()),
        )

    def _manifest_objects(self, rows: Any) -> list[CanonicalManifestObject]:
        output = []
        for row in rows if isinstance(rows, list) else ():
            if not isinstance(row, Mapping) or not isinstance(row.get("bbox"), list) or len(row["bbox"]) != 4:
                continue
            output.append(CanonicalManifestObject(
                scene_id=str(row.get("scene_id") or ""),
                role=str(row.get("role") or "object"),
                bbox=tuple(int(value) for value in row["bbox"]),
                confidence=self._float(row.get("confidence"), 1.0),
            ))
        return output

    def _manifest_assets(self, rows: Any) -> list[CanonicalManifestAsset]:
        output = []
        for index, row in enumerate(rows if isinstance(rows, list) else ()):
            if not isinstance(row, Mapping):
                continue
            path = row.get("path") or row.get("image")
            scene_id = row.get("scene_id")
            if not isinstance(path, str) or not isinstance(scene_id, str):
                continue
            bbox = row.get("bbox")
            output.append(CanonicalManifestAsset(
                id=str(row.get("id") or f"asset-{index + 1:03d}"),
                scene_id=scene_id,
                path=path,
                role=str(row.get("role") or "object"),
                bbox=(tuple(int(value) for value in bbox) if isinstance(bbox, list) and len(bbox) == 4 else None),
                confidence=self._float(row.get("confidence"), 1.0),
            ))
        return output

    @staticmethod
    def _mapping(value: Any) -> Mapping[str, Any]:
        return value if isinstance(value, Mapping) else {}

    @staticmethod
    def _indexed(rows: Any, *keys: str) -> dict[str, Mapping[str, Any]]:
        output: dict[str, Mapping[str, Any]] = {}
        for row in rows if isinstance(rows, list) else ():
            if not isinstance(row, Mapping):
                continue
            identity = next((row.get(key) for key in keys if row.get(key)), None)
            if identity is not None:
                output[str(identity)] = row
        return output

    @staticmethod
    def _string(value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @staticmethod
    def _strings(value: Any) -> tuple[str, ...]:
        if not isinstance(value, (list, tuple)):
            return ()
        return tuple(str(item) for item in value if item is not None and str(item).strip())

    @staticmethod
    def _int(value: Any) -> int | None:
        if isinstance(value, bool) or value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _float(value: Any, default: float) -> float:
        if isinstance(value, bool) or value is None:
            return default
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @classmethod
    def _enum(cls, enum_type, value):
        text = cls._string(value)
        if text is None:
            return None
        try:
            return enum_type(text.upper())
        except ValueError as exc:
            raise InvalidPackageError(
                f"unsupported canonical {enum_type.__name__}: {text}"
            ) from exc

    @classmethod
    def _span(cls, value: Any) -> CanonicalScriptSpan | None:
        if not isinstance(value, Mapping):
            return None
        return CanonicalScriptSpan(
            text=cls._string(value.get("text") or value.get("phrase")),
            global_char_start=cls._int(
                value.get("global_char_start") if value.get("global_char_start") is not None else value.get("char_start")
            ),
            global_char_end=cls._int(
                value.get("global_char_end") if value.get("global_char_end") is not None else value.get("char_end")
            ),
        )

    @classmethod
    def _locator(cls, value: Any) -> CanonicalVisualLocator | None:
        if not isinstance(value, Mapping):
            return None
        try:
            return CanonicalVisualLocator(
                coordinate_space=str(value.get("coordinate_space") or "normalized_scene"),
                cx=float(value["cx"]), cy=float(value["cy"]),
                width=float(value["width"]), height=float(value["height"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise InvalidPackageError("invalid canonical visual locator") from exc

    @classmethod
    def _continuity(cls, value: Any) -> CanonicalContinuity | None:
        if not isinstance(value, Mapping):
            return None
        return CanonicalContinuity(
            mode=cls._enum(ContinuityMode, value.get("mode")),
            target_asset_id=cls._string(value.get("target_asset_id")),
            extension_metadata=cls._extras(value, {"mode", "target_asset_id"}),
        )

    @staticmethod
    def _extras(row: Mapping[str, Any], known: Any) -> dict[str, Any]:
        keys = set(known)
        return {str(key): value for key, value in row.items() if key not in keys}


def ensure_canonical_package(package: Any) -> CanonicalPackage:
    """Return the canonical runtime representation for raw/legacy package inputs."""
    return CanonicalNormalizer().normalize(package)
