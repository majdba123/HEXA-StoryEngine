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
    story = "story"
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


class StoryBeat(BaseModel):
    id: str
    scene_id: str
    start: float
    end: float
    narration: str
    primary_asset_ids: list[str] = Field(default_factory=list)
    support_asset_ids: list[str] = Field(default_factory=list)
    action: str
    handoff_from: str | None = None
    semantic_targets: list[str] = Field(default_factory=list)


class LayoutItem(BaseModel):
    asset_id: str
    x: float
    y: float
    width: float
    height: float
    z: int = 0


class CompositionBeat(BaseModel):
    beat_id: str
    items: list[LayoutItem]


class MotionCue(BaseModel):
    beat_id: str
    asset_id: str
    kind: str
    start: float
    end: float
    params: dict[str, Any] = Field(default_factory=dict)


class RenderPlan(BaseModel):
    width: int = 1920
    height: int = 1080
    fps: int = 30
    duration: float
    story: list[StoryBeat]
    composition: list[CompositionBeat]
    motion: list[MotionCue]
    assets: list[VisualAsset]


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
