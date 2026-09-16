from __future__ import annotations

import json
from pathlib import Path

from app.models import (
    CompositionBeat,
    MotionCue,
    RenderPlan,
    StoryBeat,
    TextCompositionBeat,
    TextMotionCue,
    TextPlan,
    Transcript,
    VisualAsset,
)


class RenderPlanner:
    def compile(
        self,
        transcript: Transcript,
        assets: list[VisualAsset],
        story: list[StoryBeat],
        composition: list[CompositionBeat],
        motion: list[MotionCue],
        workspace: Path,
        *,
        text: TextPlan | None = None,
        text_composition: list[TextCompositionBeat] | None = None,
        text_motion: list[TextMotionCue] | None = None,
    ) -> tuple[RenderPlan, Path]:
        plan = RenderPlan(
            duration=transcript.duration,
            assets=assets,
            story=story,
            composition=composition,
            motion=motion,
            text=text or TextPlan(),
            text_composition=text_composition or [],
            text_motion=text_motion or [],
        )
        path = workspace / "render-plan.json"
        path.write_text(
            json.dumps(plan.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return plan, path
