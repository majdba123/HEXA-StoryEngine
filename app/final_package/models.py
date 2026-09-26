from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from app.models import SceneSource


class RawFinalPackage(BaseModel):
    """Validated source representation owned exclusively by final_package/."""

    root: Path
    package_id: str
    scenes: list[SceneSource]
    script: str | None = None
    manifest: dict[str, Any] = Field(default_factory=dict)
    scene_plan: dict[str, Any] = Field(default_factory=dict)
    semantic_bindings: dict[str, Any] = Field(default_factory=dict)
