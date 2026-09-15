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


class PackageModel(BaseModel):
    root: Path
    package_id: str
    scenes: list[SceneSource]
    script: str | None = None
    manifest: dict[str, Any] = Field(default_factory=dict)


class TranscriptSegment(BaseModel):
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    text: str

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


class VisualAsset(BaseModel):
    id: str
    scene_id: str
    role: str
    image_path: Path
    source_bbox: tuple[int, int, int, int] | None = None
    confidence: float = Field(default=1.0, ge=0, le=1)
    extraction_method: str


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
