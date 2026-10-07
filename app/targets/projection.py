"""Uniformly project a finished reference visual plan onto a target canvas."""
from __future__ import annotations

import json
from pathlib import Path

from app.models import PlanProjection, RenderPlan
from app.render.planner import RenderPlanner
from app.shared.errors import StageFailedError
from app.targets.models import VisualTargetProfile


class ReferencePlanProjector:
    def project(self, reference: RenderPlan, target: VisualTargetProfile, workspace: Path) -> RenderPlan:
        if (reference.width, reference.height, reference.fps) != (1920, 1080, target.fps):
            raise StageFailedError("reference frame cannot be projected", details={"code": "TARGET_PROJECTION_INVALID"})
        if reference.projection is not None or target.layout_policy != "reference_projection":
            raise StageFailedError("target requires a finished reference plan", details={"code": "TARGET_PROJECTION_INVALID"})

        safe = target.safe_zones.content
        left, top = safe.left * target.width, safe.top * target.height
        safe_width = safe.width * target.width
        safe_height = safe.height * target.height
        scale = min(safe_width / reference.width, safe_height / reference.height)
        offset_x = left + (safe_width - reference.width * scale) / 2
        offset_y = top + (safe_height - reference.height * scale) / 2
        projection = PlanProjection(reference_width=reference.width, reference_height=reference.height,
                                    scale=scale, offset_x=offset_x, offset_y=offset_y)

        def x(value: float) -> float:
            return (offset_x + value * reference.width * scale) / target.width

        def y(value: float) -> float:
            return (offset_y + value * reference.height * scale) / target.height

        def dx(value: float) -> float:
            return value * reference.width * scale / target.width

        def dy(value: float) -> float:
            return value * reference.height * scale / target.height

        plan = reference.model_copy(deep=True)
        plan.target_id, plan.width, plan.height = target.target_id, target.width, target.height
        plan.projection = projection
        for beat in plan.composition:
            for item in beat.items:
                item.x, item.y = x(item.x), y(item.y)
                item.width, item.height = dx(item.width), dy(item.height)
                item.placement_source = "projected_reference"
        for beat in plan.text_composition:
            for item in beat.items:
                item.x, item.y = x(item.x), y(item.y)
                item.max_width = dx(item.max_width)
                # font_scale is a dimensionless authoring multiplier.
        for cue in plan.motion:
            self._reject_unknown_spatial_fields(cue.params)
            programs = [cue.params.get("program"), *(segment.program for segment in cue.segments)]
            for program in programs:
                if not isinstance(program, dict):
                    continue
                self._reject_unknown_spatial_fields(program)
                for frame in program.get("keyframes", []):
                    frame["dx"] = dx(float(frame.get("dx", 0.0)))
                    frame["dy"] = dy(float(frame.get("dy", 0.0)))
                    # scale, easing, progress and semantic timing are unchanged.

        RenderPlanner._require_executable(plan)
        workspace.mkdir(parents=True, exist_ok=True)
        (workspace / "render-plan.json").write_text(
            json.dumps(plan.model_dump(mode="json"), ensure_ascii=False, indent=2), encoding="utf-8",
        )
        diagnostics = workspace / "diagnostics"
        diagnostics.mkdir(parents=True, exist_ok=True)
        (diagnostics / "projection.json").write_text(
            json.dumps(projection.model_dump(mode="json"), indent=2), encoding="utf-8",
        )
        return plan

    @staticmethod
    def _reject_unknown_spatial_fields(value: object) -> None:
        """New motion geometry must be explicitly added to this projector first."""
        forbidden = {"x", "y", "width", "height", "offset_x", "offset_y",
                     "control_x", "control_y", "amplitude_x", "amplitude_y"}
        if isinstance(value, dict):
            for key, child in value.items():
                if key in forbidden and isinstance(child, (int, float)):
                    raise StageFailedError(
                        "unprojected motion geometry", details={"code": "TARGET_PROJECTION_INVALID", "field": key},
                    )
                ReferencePlanProjector._reject_unknown_spatial_fields(child)
        elif isinstance(value, list):
            for child in value:
                ReferencePlanProjector._reject_unknown_spatial_fields(child)
