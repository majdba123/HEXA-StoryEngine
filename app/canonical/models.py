from __future__ import annotations

from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .enums import (
    AnchorGranularity,
    BindingType,
    CompoundVisualClassification,
    ContinuityMode,
    SemanticGroupAnimationPolicy,
    VisualFocus,
)


class CanonicalRecord(BaseModel, Mapping[str, Any]):
    """Typed canonical record with a read-only mapping compatibility surface.

    The mapping surface exists only to keep proven legacy algorithms behavior-identical
    during migration. Values originate from typed canonical fields, never raw JSON.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    def __getitem__(self, key: str) -> Any:
        if key not in type(self).model_fields:
            raise KeyError(key)
        return getattr(self, key)

    def __iter__(self) -> Iterator[str]:
        return iter(type(self).model_fields)

    def __len__(self) -> int:
        return len(type(self).model_fields)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)


class CanonicalScriptSpan(CanonicalRecord):
    text: str | None = None
    global_char_start: int | None = None
    global_char_end: int | None = None


class CanonicalVisualLocator(CanonicalRecord):
    coordinate_space: str = "normalized_scene"
    cx: float
    cy: float
    width: float
    height: float


class CanonicalContinuity(CanonicalRecord):
    mode: ContinuityMode | None = None
    target_asset_id: str | None = None
    extension_metadata: dict[str, Any] = Field(default_factory=dict)


class CanonicalAsset(CanonicalRecord):
    unit_id: str
    asset_id: str
    scene_id: str
    type: str = "VISUAL_ASSET_INTENT"
    semantic_name: str | None = None
    visual_concept: str | None = None
    semantic_meaning: str | None = None
    role: str | None = None
    semantic_role: str | None = None
    semantic_intent: str | None = None
    narrative_function: str | None = None
    binding_type: BindingType | None = None
    script_text: str | None = None
    script_span: CanonicalScriptSpan | None = None
    appear_trigger: CanonicalScriptSpan | None = None
    focus_trigger: CanonicalScriptSpan | None = None
    exit_trigger: CanonicalScriptSpan | None = None
    semantic_group_id: str | None = None
    sequence_order: int | None = None
    parent_asset_id: str | None = None
    children_asset_ids: tuple[str, ...] = ()
    confidence: float = 1.0
    interaction_target: str | None = None
    relationship: str | None = None
    semantic_event_id: str | None = None
    anchor_granularity: AnchorGranularity | None = None
    visual_focus: VisualFocus | None = None
    visual_state: dict[str, str] | None = None
    continuity: CanonicalContinuity | None = None
    compound_visual_classification: CompoundVisualClassification | None = None
    internal_progression_unavailable: bool = False
    needs_review: bool = False
    ambiguity_reason: str | None = None
    visual_locator: CanonicalVisualLocator | None = None
    extension_metadata: dict[str, Any] = Field(default_factory=dict)


class CanonicalSemanticGroup(CanonicalRecord):
    semantic_group_id: str
    script_text: str | None = None
    animation_policy: SemanticGroupAnimationPolicy = (
        SemanticGroupAnimationPolicy.SEQUENTIAL_WITHIN_PHRASE
    )
    asset_ids: tuple[str, ...] = ()
    extension_metadata: dict[str, Any] = Field(default_factory=dict)


class CanonicalSemanticEvent(CanonicalRecord):
    semantic_event_id: str
    scene_id: str
    script_text: str | None = None
    script_span: CanonicalScriptSpan | None = None
    anchor_granularity: AnchorGranularity | None = None
    sequence_order: int | None = None
    visual_leader_asset_id: str | None = None
    participant_asset_ids: tuple[str, ...] = ()
    context_asset_ids: tuple[str, ...] = ()
    result_asset_ids: tuple[str, ...] = ()
    text_anchor_asset_id: str | None = None
    confidence: float = 1.0
    needs_review: bool = False
    ambiguity_reason: str | None = None
    depends_on_event_ids: tuple[str, ...] = ()
    extension_metadata: dict[str, Any] = Field(default_factory=dict)


class CanonicalRelation(CanonicalRecord):
    subject_asset_id: str
    relation_type: str
    object_asset_id: str
    result_asset_id: str | None = None
    script_text: str | None = None
    script_span: CanonicalScriptSpan | None = None
    confidence: float = 1.0
    extension_metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def relationship(self) -> str:
        return self.relation_type


class CanonicalProgression(CanonicalRecord):
    type: str | None = None
    event_order: tuple[str, ...] = ()
    extension_metadata: dict[str, Any] = Field(default_factory=dict)


class CanonicalVisualProgression(CanonicalRecord):
    action: str = "EXPLAIN"
    targets: tuple[str, ...] = ()
    trigger: CanonicalScriptSpan | None = None
    extension_metadata: dict[str, Any] = Field(default_factory=dict)


class CanonicalScene(CanonicalRecord):
    id: str
    image_path: Path
    order: int
    title: str | None = None
    narration_hint: str | None = None
    script_char_start: int | None = None
    script_char_end: int | None = None
    purpose: str | None = None
    visual_concept: str | None = None
    relation_to_previous: str | None = None
    character_category: str | None = None
    units: tuple[CanonicalAsset, ...] = ()
    visual_progression: tuple[CanonicalVisualProgression, ...] = ()
    semantic_events: tuple[CanonicalSemanticEvent, ...] = ()
    semantic_groups: tuple[CanonicalSemanticGroup, ...] = ()
    relations: tuple[CanonicalRelation, ...] = ()
    semantic_progression: CanonicalProgression | None = None
    extension_metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def scene_id(self) -> str:
        return self.id

    @property
    def assets(self) -> tuple[CanonicalAsset, ...]:
        return tuple(unit for unit in self.units if unit.type.upper() == "VISUAL_ASSET_INTENT")

    @property
    def progression(self) -> CanonicalProgression | None:
        return self.semantic_progression


class CanonicalManifestObject(CanonicalRecord):
    scene_id: str
    role: str = "object"
    bbox: tuple[int, int, int, int]
    confidence: float = 1.0


class CanonicalManifestAsset(CanonicalRecord):
    id: str
    scene_id: str
    path: str
    role: str = "object"
    bbox: tuple[int, int, int, int] | None = None
    confidence: float = 1.0


class CanonicalPackage(CanonicalRecord):
    root: Path
    package_id: str
    script: str | None = None
    schema_name: str | None = None
    schema_version: str | None = None
    scenes: tuple[CanonicalScene, ...]
    manifest_objects: tuple[CanonicalManifestObject, ...] = ()
    manifest_assets: tuple[CanonicalManifestAsset, ...] = ()
    semantic_binding_schema_name: str | None = None
    semantic_binding_schema_version: str | None = None
    semantic_bindings_present: bool = False
    extension_metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def scene_by_id(self) -> dict[str, CanonicalScene]:
        return {scene.id: scene for scene in self.scenes}

    @property
    def asset_by_id(self) -> dict[str, CanonicalAsset]:
        return {
            asset.asset_id: asset
            for scene in self.scenes
            for asset in scene.units
            if asset.type.upper() == "VISUAL_ASSET_INTENT"
        }

    @property
    def event_by_id(self) -> dict[str, CanonicalSemanticEvent]:
        return {
            event.semantic_event_id: event
            for scene in self.scenes
            for event in scene.semantic_events
        }

    @property
    def has_semantic_bindings(self) -> bool:
        return self.semantic_bindings_present
