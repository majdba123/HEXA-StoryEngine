from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator


class JobState(StrEnum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"


class Stage(StrEnum):
    input = "input"
    transcription = "transcription"
    vision = "vision"
    cutout = "cutout"
    refinement = "refinement"
    story = "story"
    text = "text"
    composition = "composition"
    motion = "motion"
    render = "render"
    final = "final"
    recovery = "recovery"


class SceneSource(BaseModel):
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
    units: list[dict[str, Any]] = Field(default_factory=list)
    visual_progression: list[dict[str, Any]] = Field(default_factory=list)


class PackageModel(BaseModel):
    root: Path
    package_id: str
    scenes: list[SceneSource]
    script: str | None = None
    manifest: dict[str, Any] = Field(default_factory=dict)
    scene_plan: dict[str, Any] = Field(default_factory=dict)


class TranscriptWord(BaseModel):
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    text: str
    char_start: int | None = None
    char_end: int | None = None

    @field_validator("text")
    @classmethod
    def word_non_empty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("transcript word cannot be empty")
        return value


class TranscriptSegment(BaseModel):
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    text: str
    char_start: int | None = None
    char_end: int | None = None
    words: list[TranscriptWord] = Field(default_factory=list)

    @field_validator("text")
    @classmethod
    def non_empty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("transcript segment cannot be empty")
        return value


class Transcript(BaseModel):
    language: str | None = None
    duration: float = Field(gt=0)
    segments: list[TranscriptSegment]
    words: list[TranscriptWord] = Field(default_factory=list)
    timing_source: str = "unknown"


class VisualAsset(BaseModel):
    id: str
    scene_id: str
    role: str
    image_path: Path
    source_bbox: tuple[int, int, int, int] | None = None
    confidence: float = Field(default=1.0, ge=0, le=1)
    extraction_method: str
    independent: bool = True
    compound: bool = False
    component_count: int = Field(default=1, ge=1)
    source_area_ratio: float | None = Field(default=None, ge=0, le=1)
    source_canvas_width: int | None = Field(default=None, gt=0)
    source_canvas_height: int | None = Field(default=None, gt=0)
    can_animate_independently: bool = True
    parent_asset_id: str | None = None
    asset_family_id: str | None = None
    render_as_family_canvas: bool = False


class StoryTrigger(BaseModel):
    phrase: str | None = None
    occurrence_in_scene: int | None = None
    global_char_start: int | None = None
    global_char_end: int | None = None


class StoryEntity(BaseModel):
    unit_id: str
    semantic_name: str | None = None
    entity_type: str | None = None
    role: str | None = None
    narrative_function: str | None = None
    semantic_intent: str | None = None
    appear_trigger: StoryTrigger | None = None
    focus_trigger: StoryTrigger | None = None
    exit_trigger: StoryTrigger | None = None
    package_metadata: dict[str, Any] = Field(default_factory=dict)


class StoryRelation(BaseModel):
    source_unit_id: str
    target_unit_id: str
    kind: str
    authority: str
    confidence: float = Field(default=1.0, ge=0, le=1)
    causal: bool = False


class StorySemanticContext(BaseModel):
    story_role: str = "CONTEXT"
    event_id: str | None = None
    event_order: int | None = None
    event_trigger: StoryTrigger | None = None
    scene_purpose: str | None = None
    scene_visual_concept: str | None = None
    scene_metadata: dict[str, Any] = Field(default_factory=dict)
    event_metadata: dict[str, Any] = Field(default_factory=dict)
    entities: list[StoryEntity] = Field(default_factory=list)
    relations: list[StoryRelation] = Field(default_factory=list)
    subject_unit_ids: list[str] = Field(default_factory=list)
    object_unit_ids: list[str] = Field(default_factory=list)
    result_unit_ids: list[str] = Field(default_factory=list)
    narrative_functions: list[str] = Field(default_factory=list)
    semantic_intents: list[str] = Field(default_factory=list)
    continuity_relation: str | None = None
    evidence: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0, le=1)
    tension: float = Field(default=0.0, ge=0, le=1)


class StoryBeat(BaseModel):
    id: str
    scene_id: str
    start: float
    end: float
    audio_start: float | None = None
    audio_end: float | None = None
    narration: str
    primary_asset_ids: list[str] = Field(default_factory=list)
    support_asset_ids: list[str] = Field(default_factory=list)
    action: str
    handoff_from: str | None = None
    semantic_targets: list[str] = Field(default_factory=list)
    semantic_context: StorySemanticContext | None = None


class LayoutItem(BaseModel):
    asset_id: str
    x: float
    y: float
    width: float
    height: float
    z: int = 0
    placement_source: str = "authored"


class CompositionBeat(BaseModel):
    beat_id: str
    items: list[LayoutItem]
    state_name: str = "AUTHORED"
    semantic_focus_asset_id: str | None = None
    state_evidence: list[str] = Field(default_factory=list)


class MotionCue(BaseModel):
    beat_id: str
    asset_id: str
    kind: str
    start: float
    end: float
    params: dict[str, Any] = Field(default_factory=dict)


class TextTokenCue(BaseModel):
    text: str
    source_char_start: int = Field(ge=0)
    source_char_end: int = Field(gt=0)
    spoken_start: float = Field(ge=0)
    spoken_end: float = Field(gt=0)

    @field_validator("text")
    @classmethod
    def token_text_non_empty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("text token cannot be empty")
        return value


class TextCue(BaseModel):
    id: str
    beat_id: str
    text: str
    semantic_type: str
    source_char_start: int = Field(ge=0)
    source_char_end: int = Field(gt=0)
    spoken_start: float = Field(ge=0)
    spoken_end: float = Field(gt=0)
    emphasis_time: float = Field(ge=0)
    anchor_asset_id: str | None = None
    priority: int = 0
    style_id: str
    placement_hint: str | None = None
    story_role: str | None = None
    choreography_action: str | None = None
    semantic_unit_ids: list[str] = Field(default_factory=list)
    relationship: str | None = None
    package_evidence: list[str] = Field(default_factory=list)
    tokens: list[TextTokenCue] = Field(default_factory=list)

    @field_validator("text")
    @classmethod
    def text_non_empty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("text cue cannot be empty")
        return value


class TextStyle(BaseModel):
    id: str
    role: str
    font_role: str
    size_role: str
    color_role: str
    background_role: str
    emphasis_role: str


class TextPlan(BaseModel):
    cues: list[TextCue] = Field(default_factory=list)
    styles: list[TextStyle] = Field(default_factory=list)


class TextLayoutItem(BaseModel):
    text_cue_id: str
    x: float
    y: float
    max_width: float
    font_scale: float = Field(default=1.0, ge=0.55, le=1.0)
    z: int = 50
    anchor_asset_id: str | None = None
    placement: str = "safe_top"


class TextCompositionBeat(BaseModel):
    beat_id: str
    items: list[TextLayoutItem] = Field(default_factory=list)


class TextMotionToken(BaseModel):
    text: str
    start: float
    end: float
    visible_end: float
    kind: str = "text_word_in"


class TextMotionCue(BaseModel):
    beat_id: str
    text_cue_id: str
    kind: str
    start: float
    end: float
    params: dict[str, Any] = Field(default_factory=dict)
    tokens: list[TextMotionToken] = Field(default_factory=list)


class RenderPlan(BaseModel):
    width: int = 1920
    height: int = 1080
    fps: int = 30
    duration: float
    story: list[StoryBeat]
    composition: list[CompositionBeat]
    motion: list[MotionCue]
    assets: list[VisualAsset]
    text: TextPlan = Field(default_factory=TextPlan)
    text_composition: list[TextCompositionBeat] = Field(default_factory=list)
    text_motion: list[TextMotionCue] = Field(default_factory=list)


class JobRequest(BaseModel):
    package_path: str
    audio_path: str
    script_path: str | None = None
    output_name: str | None = None


class JobSnapshot(BaseModel):
    id: str
    state: JobState
    stage: Stage | None = None
    progress: float = Field(default=0, ge=0, le=1)
    message: str = ""
    output_path: str | None = None
    error_code: str | None = None
