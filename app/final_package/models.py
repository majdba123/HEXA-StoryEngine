from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ScriptSpanPayload(StrictModel):
    text: str | None
    global_char_start: int | None
    global_char_end: int | None


class VisualLocatorPayload(StrictModel):
    coordinate_space: str | None
    cx: float | None
    cy: float | None
    width: float | None
    height: float | None


class VisualStatePayload(StrictModel):
    before: str | None
    after: str | None


class ContinuityPayload(StrictModel):
    mode: str | None
    target_asset_id: str | None


class UnifiedObjectPayload(StrictModel):
    unit_id: str
    asset_id: str
    scene_id: str
    object_type: str
    source_asset_id: str | None
    semantic_name: str | None
    visual_concept: str | None
    semantic_meaning: str | None
    role: str | None
    semantic_role: str | None
    semantic_intent: str | None
    narrative_function: str | None
    binding_type: str | None
    script_text: str | None
    script_span: ScriptSpanPayload
    appear_trigger: ScriptSpanPayload
    focus_trigger: ScriptSpanPayload
    exit_trigger: ScriptSpanPayload
    semantic_group_id: str | None
    sequence_order: int | None
    parent_asset_id: str | None
    children_asset_ids: list[str]
    confidence: float
    interaction_target: str | None
    relationship: str | None
    semantic_event_id: str | None
    anchor_granularity: str | None
    visual_focus: str | None
    visual_state: VisualStatePayload
    continuity: ContinuityPayload
    compound_visual_classification: str | None
    internal_progression_unavailable: bool
    needs_review: bool
    ambiguity_reason: str | None
    visual_locator: VisualLocatorPayload


class VisualProgressionPayload(StrictModel):
    action: str
    event_id: str | None
    order: int | None
    targets: list[str]
    trigger: ScriptSpanPayload


class SemanticGroupPayload(StrictModel):
    semantic_group_id: str
    script_text: str | None
    animation_policy: str
    asset_ids: list[str]


class SemanticEventPayload(StrictModel):
    semantic_event_id: str
    scene_id: str
    script_text: str | None
    script_span: ScriptSpanPayload
    anchor_granularity: str | None
    sequence_order: int | None
    visual_leader_asset_id: str | None
    participant_asset_ids: list[str]
    context_asset_ids: list[str]
    result_asset_ids: list[str]
    text_anchor_asset_id: str | None
    confidence: float
    needs_review: bool
    ambiguity_reason: str | None
    depends_on_event_ids: list[str]


class RelationPayload(StrictModel):
    relation_id: str | None
    subject_asset_id: str
    relation_type: str | None
    relationship: str | None
    object_asset_id: str
    result_asset_id: str | None
    connector_asset_id: str | None
    script_text: str | None
    script_span: ScriptSpanPayload
    confidence: float


class SemanticProgressionPayload(StrictModel):
    type: str | None
    event_order: list[str]


class UnifiedScenePayload(StrictModel):
    scene_id: str
    order: int
    image: str
    title: str | None
    narration_hint: str | None
    script_span: ScriptSpanPayload
    purpose: str | None
    visual_concept: str | None
    relation_to_previous: str | None
    character_category: str | None
    objects: list[UnifiedObjectPayload]
    visual_progression: list[VisualProgressionPayload]
    semantic_groups: list[SemanticGroupPayload]
    semantic_events: list[SemanticEventPayload]
    relations: list[RelationPayload]
    semantic_progression: SemanticProgressionPayload


class ImageSpecPayload(StrictModel):
    directory: str
    format: str
    width: int
    height: int


class SourceProvenancePayload(StrictModel):
    source_contract_version: str
    source_package_name: str
    source_sha256: str
    conversion_mode: str


class UnifiedFinalPackagePayload(StrictModel):
    contract: Literal["HEXA_UNIFIED_FINAL_PACKAGE"]
    contract_version: Literal["2.0"]
    package_id: str
    project_slug: str
    language: str
    builder_target: str
    timing_authority: str
    script_audio_relationship: str
    canonical_script: str
    image_spec: ImageSpecPayload
    source_provenance: SourceProvenancePayload
    scenes: list[UnifiedScenePayload]
