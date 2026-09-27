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
from app.shared.errors import StageFailedError


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
        self._require_executable(plan)
        path = workspace / "render-plan.json"
        path.write_text(
            json.dumps(plan.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return plan, path

    @staticmethod
    def _require_executable(plan: RenderPlan) -> None:
        assets = {asset.id: asset for asset in plan.assets}
        beats = {beat.id: beat for beat in plan.story}
        for asset in plan.assets:
            if not asset.image_path.is_file():
                raise StageFailedError(
                    f"Asset file is missing: {asset.id}",
                    details={"code": "ASSET_BAD_CUTOUT", "asset_id": asset.id},
                )
        for beat in plan.story:
            if beat.action == "HANDOFF" and not beat.handoff_from:
                raise StageFailedError(
                    f"Handoff has no source: {beat.id}",
                    details={"code": "BAD_HANDOFF", "beat_id": beat.id},
                )
            for asset_id in beat.primary_asset_ids + beat.support_asset_ids:
                if asset_id not in assets:
                    raise StageFailedError(
                        f"Story references unknown asset: {asset_id}",
                        details={
                            "code": "ASSET_BAD_CUTOUT",
                            "asset_id": asset_id,
                            "beat_id": beat.id,
                        },
                    )
        for composition in plan.composition:
            if composition.beat_id not in beats:
                raise StageFailedError(
                    f"Composition references unknown beat: {composition.beat_id}",
                    details={"code": "STAGE_FAILED", "beat_id": composition.beat_id},
                )
            for item in composition.items:
                if item.asset_id not in assets:
                    raise StageFailedError(
                        f"Composition references unknown asset: {item.asset_id}",
                        details={"code": "ASSET_BAD_CUTOUT", "asset_id": item.asset_id},
                    )
        for cue in plan.motion:
            if cue.beat_id not in beats or cue.asset_id not in assets:
                raise StageFailedError(
                    "Motion references an unknown beat or asset",
                    details={
                        "code": "STAGE_FAILED",
                        "beat_id": cue.beat_id,
                        "asset_id": cue.asset_id,
                    },
                )
