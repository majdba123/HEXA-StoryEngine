from __future__ import annotations

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


class FrozenDict(dict):
    """Recursively immutable mapping used for canonical extension metadata."""

    @staticmethod
    def _immutable(*_args: Any, **_kwargs: Any) -> None:
        raise TypeError("canonical mapping is immutable")

    __setitem__ = _immutable
    __delitem__ = _immutable
    clear = _immutable
    pop = _immutable
    popitem = _immutable
    setdefault = _immutable
    update = _immutable
    __ior__ = _immutable


def _freeze_canonical_value(value: Any) -> Any:
    if isinstance(value, FrozenDict):
        return value
    if isinstance(value, dict):
        return FrozenDict({key: _freeze_canonical_value(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze_canonical_value(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_freeze_canonical_value(item) for item in value)
    if isinstance(value, set):
        return frozenset(_freeze_canonical_value(item) for item in value)
    if isinstance(value, frozenset):
        return frozenset(_freeze_canonical_value(item) for item in value)
    return value


class CanonicalRecord(BaseModel):
    """Typed, deeply immutable canonical semantic truth."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    def model_post_init(self, __context: Any) -> None:
        del __context
        for field_name in type(self).model_fields:
            current = getattr(self, field_name)
            frozen = _freeze_canonical_value(current)
            if frozen is not current:
                object.__setattr__(self, field_name, frozen)


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
    source_asset_id: str | None = None
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

    @property
    def priority_role_conflict(self) -> bool:
        """Only compare role values when both describe presentation priority."""
        presentation = (self.role or "").casefold()
        semantic = (self.semantic_role or "").casefold()
        return (
            (presentation == "primary" and semantic in {"support", "supporting", "decorative"})
            or (presentation in {"support", "supporting", "decorative"} and semantic == "primary")
        )


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
    relation_id: str | None = None
    subject_asset_id: str
    relation_type: str
    object_asset_id: str
    result_asset_id: str | None = None
    connector_asset_id: str | None = None
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
    event_id: str | None = None
    order: int | None = None
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

    @property
    def semantic_carrier_roles(self) -> dict[str, tuple[str, ...]]:
        """Authored assets that must own a visible runtime carrier, with their roles.

        Event leaders, participants, results and text anchors plus explicit visual
        progression targets are required semantic participation. Event context and
        unreferenced units stay optional, so presentation roles such as ``decorative``
        never outrank explicit event participation.
        """
        roles: dict[str, list[str]] = {}

        def add(asset_id: str | None, role: str) -> None:
            key = str(asset_id or "").strip()
            if key and role not in roles.setdefault(key, []):
                roles[key].append(role)

        for event in self.semantic_events:
            add(event.visual_leader_asset_id, "LEADER")
            for asset_id in event.participant_asset_ids:
                add(asset_id, "PARTICIPANT")
            for asset_id in event.result_asset_ids:
                add(asset_id, "RESULT")
            add(event.text_anchor_asset_id, "TEXT_ANCHOR")
        unit_ids = {unit.asset_id for unit in self.units}
        for step in self.visual_progression:
            for target in step.targets:
                if target in unit_ids:
                    add(target, "PROGRESSION_TARGET")
        return {asset_id: tuple(values) for asset_id, values in roles.items()}


class CanonicalPackage(CanonicalRecord):
    root: Path
    package_id: str
    script: str | None = None
    contract_name: str = "HEXA_UNIFIED_FINAL_PACKAGE"
    contract_version: str = "2.0"
    language: str | None = None
    project_slug: str | None = None
    builder_target: str | None = None
    timing_authority: str | None = None
    script_audio_relationship: str | None = None
    has_authoritative_semantics: bool = True
    scenes: tuple[CanonicalScene, ...]
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
