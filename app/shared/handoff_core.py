from __future__ import annotations

from collections import Counter
from math import isfinite
from typing import Iterable

from app.models import VisualAsset
from app.shared.errors import StageFailedError

_EPS = 1e-8
_MAX_VIOLATIONS = 40


class _HandoffCore:
    @staticmethod
    def _directive_asset_refs(directive) -> set[str]:
        refs = {
            asset_id
            for asset_id in (
                directive.primary_asset_id,
                directive.interaction_asset_id,
                *directive.actor_asset_ids,
                *directive.support_asset_ids,
            )
            if asset_id
        }
        interactions = directive.interactions or (
            (directive.interaction,) if directive.interaction is not None else ()
        )
        for interaction in interactions:
            refs.update(
                asset_id
                for asset_id in (
                    interaction.subject_asset_id,
                    interaction.object_asset_id,
                    interaction.result_asset_id,
                )
                if asset_id
            )
        for transition in directive.state_transitions:
            if transition.asset_id:
                refs.add(transition.asset_id)
        for requirement in directive.asset_requirements:
            if requirement.bound_asset_id:
                refs.add(requirement.bound_asset_id)
        for flow in directive.event_flows:
            refs.update(flow.asset_ids)
            refs.update(flow.handoff_to_asset_ids)
            if flow.handoff_to_asset_id:
                refs.add(flow.handoff_to_asset_id)
            for step in flow.steps:
                refs.update(
                    asset_id
                    for asset_id in (
                        step.focus_asset_id,
                        step.source_asset_id,
                        step.target_asset_id,
                        step.result_asset_id,
                        *step.participant_asset_ids,
                    )
                    if asset_id
                )
        return refs

    @classmethod
    def _validate_segment_program(
        cls,
        violations: list[dict[str, object]],
        *,
        beat_id: str,
        asset_id: str,
        phase: str,
        program: dict,
        kind_prefix: str = "motion_segment",
    ) -> None:
        if not program:
            cls._add(
                violations,
                f"{kind_prefix}_program_missing",
                beat_id=beat_id,
                asset_id=asset_id,
                phase=phase,
            )
            return
        keyframes = program.get("keyframes")
        if not isinstance(keyframes, list) or len(keyframes) < 2:
            cls._add(
                violations,
                f"{kind_prefix}_keyframes_missing",
                beat_id=beat_id,
                asset_id=asset_id,
                phase=phase,
            )
            return
        progresses: list[float] = []
        for frame in keyframes:
            if not isinstance(frame, dict):
                cls._add(
                    violations,
                    f"{kind_prefix}_invalid_keyframe",
                    beat_id=beat_id,
                    asset_id=asset_id,
                    phase=phase,
                )
                return
            try:
                progress = float(frame.get("progress"))
                dx = float(frame.get("dx", 0.0))
                dy = float(frame.get("dy", 0.0))
                scale = float(frame.get("scale", 1.0))
            except (TypeError, ValueError, OverflowError):
                cls._add(
                    violations,
                    f"{kind_prefix}_non_numeric_keyframe",
                    beat_id=beat_id,
                    asset_id=asset_id,
                    phase=phase,
                )
                return
            if not all(isfinite(value) for value in (progress, dx, dy, scale)):
                cls._add(
                    violations,
                    f"{kind_prefix}_nonfinite_keyframe",
                    beat_id=beat_id,
                    asset_id=asset_id,
                    phase=phase,
                )
                return
            progresses.append(progress)
        if (
            abs(progresses[0]) > _EPS
            or abs(progresses[-1] - 1.0) > _EPS
            or any(right <= left for left, right in zip(progresses, progresses[1:]))
        ):
            cls._add(
                violations,
                f"{kind_prefix}_invalid_keyframe_progress",
                beat_id=beat_id,
                asset_id=asset_id,
                phase=phase,
                progress=progresses,
            )
        if str(program.get("terminal_behavior") or "").upper() == "LEAVE":
            return
        final = keyframes[-1]
        try:
            final_dx = float(final.get("dx", 0.0))
            final_dy = float(final.get("dy", 0.0))
            final_scale = float(final.get("scale", 1.0))
        except (TypeError, ValueError, OverflowError):
            return
        if (
            abs(final_dx) > _EPS
            or abs(final_dy) > _EPS
            or abs(final_scale - 1.0) > _EPS
        ):
            cls._add(
                violations,
                f"{kind_prefix}_does_not_restore_composition_identity",
                beat_id=beat_id,
                asset_id=asset_id,
                phase=phase,
                dx=final_dx,
                dy=final_dy,
                scale=final_scale,
            )

    @staticmethod
    def _window(
        start: float,
        end: float,
        *,
        lower: float,
        upper: float,
        allow_equal: bool = False,
    ) -> bool:
        if not all(isfinite(float(value)) for value in (start, end, lower, upper)):
            return False
        ordered = start <= end if allow_equal else start < end
        return bool(
            ordered
            and start >= lower - _EPS
            and end <= upper + _EPS
        )

    @classmethod
    def _require_asset_scene(
        cls,
        violations: list[dict[str, object]],
        *,
        asset_by_id: dict[str, VisualAsset],
        asset_id: str,
        scene_id: str,
        kind: str,
        **context: object,
    ) -> None:
        asset = asset_by_id.get(asset_id)
        if asset is None:
            cls._add(
                violations,
                f"{kind}_unknown_asset",
                asset_id=asset_id,
                scene_id=scene_id,
                **context,
            )
        elif asset.scene_id != scene_id:
            cls._add(
                violations,
                f"{kind}_cross_scene",
                asset_id=asset_id,
                expected_scene_id=scene_id,
                actual_scene_id=asset.scene_id,
                **context,
            )

    @classmethod
    def _duplicates(
        cls,
        values: Iterable[object],
        *,
        kind: str,
        field: str,
        violations: list[dict[str, object]],
        context: dict[str, object] | None = None,
    ) -> None:
        rows = list(values)
        counts = Counter(rows)
        for value, count in counts.items():
            if count <= 1:
                continue
            payload = dict(context or {})
            payload[field] = value
            payload["count"] = count
            cls._add(violations, kind, **payload)

    @staticmethod
    def _add(
        violations: list[dict[str, object]],
        kind: str,
        **details: object,
    ) -> None:
        if len(violations) >= _MAX_VIOLATIONS:
            return
        violations.append({"kind": kind, **details})

    @staticmethod
    def _raise(
        boundary: str,
        code: str,
        violations: list[dict[str, object]],
    ) -> None:
        if not violations:
            return
        raise StageFailedError(
            f"Cross-layer handoff contract failed at {boundary}",
            details={
                "code": code,
                "boundary": boundary,
                "violation_count": len(violations),
                "violations": violations,
            },
        )
