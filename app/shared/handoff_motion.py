from __future__ import annotations

from app.choreography import ChoreographyPlan
from app.models import CompositionBeat, MotionCue, StoryBeat, VisualAsset
from app.motion.timing import projected_motion_activity_px, semantic_readability_floor_px

from .handoff_core import _EPS, _HandoffCore


class MotionHandoffMixin(_HandoffCore):
    @classmethod
    def require_motion_for_text_and_render(
        cls,
        *,
        story: list[StoryBeat],
        assets: list[VisualAsset],
        composition: list[CompositionBeat],
        choreography: ChoreographyPlan,
        motion: list[MotionCue],
    ) -> None:
        violations: list[dict[str, object]] = []
        beat_by_id = {beat.id: beat for beat in story}
        directive_by_beat = {directive.beat_id: directive for directive in choreography.directives}
        asset_by_id = {asset.id: asset for asset in assets}
        layout_by_beat = {layout.beat_id: layout for layout in composition}
        cue_pairs = [(cue.beat_id, cue.asset_id) for cue in motion]
        cls._duplicates(
            cue_pairs,
            kind="duplicate_motion_cue",
            field="beat_asset",
            violations=violations,
        )

        cues_by_beat: dict[str, set[str]] = {}
        for cue in motion:
            cues_by_beat.setdefault(cue.beat_id, set()).add(cue.asset_id)
            beat = beat_by_id.get(cue.beat_id)
            if beat is None:
                cls._add(
                    violations,
                    "motion_unknown_beat",
                    beat_id=cue.beat_id,
                    asset_id=cue.asset_id,
                )
                continue
            cls._require_asset_scene(
                violations,
                asset_by_id=asset_by_id,
                asset_id=cue.asset_id,
                scene_id=beat.scene_id,
                kind="motion_asset_reference",
                beat_id=beat.id,
            )
            layout = layout_by_beat.get(beat.id)
            layout_ids = {item.asset_id for item in layout.items} if layout else set()
            if cue.asset_id not in layout_ids:
                cls._add(
                    violations,
                    "motion_asset_missing_from_composition",
                    beat_id=beat.id,
                    asset_id=cue.asset_id,
                )
            if not cls._window(
                cue.start,
                cue.end,
                lower=beat.start,
                upper=beat.end,
                allow_equal=True,
            ):
                cls._add(
                    violations,
                    "motion_cue_window_outside_beat",
                    beat_id=beat.id,
                    asset_id=cue.asset_id,
                    start=cue.start,
                    end=cue.end,
                    beat_start=beat.start,
                    beat_end=beat.end,
                )

            base_program = dict(cue.params.get("program") or {})
            cls._validate_segment_program(
                violations,
                beat_id=beat.id,
                asset_id=cue.asset_id,
                phase="ENTRY",
                program=base_program,
                kind_prefix="motion_cue",
            )
            layout_item = next(
                (item for item in (layout.items if layout else []) if item.asset_id == cue.asset_id),
                None,
            )
            render_constraints = (
                cue.params.get("render_constraints", {})
                if isinstance(cue.params, dict)
                else {}
            )
            geometry_locked = (
                isinstance(render_constraints, dict)
                and render_constraints.get("geometry_lock") == "authored_footprint"
            )
            if layout_item is not None and not geometry_locked:
                cls._validate_entry_renderability(
                    violations,
                    beat_id=beat.id,
                    asset_id=cue.asset_id,
                    item=layout_item,
                    duration=max(0.0, float(cue.end) - float(cue.start)),
                    program=base_program,
                    kind="motion_cue_entry_render_dead_zone",
                )
            story_event_ids = {
                activation.semantic_event_id
                for activation in beat.asset_activations
                if activation.semantic_event_id
            }
            story_event_ids.update(
                proxy.semantic_event_id for proxy in beat.semantic_event_proxies
            )
            directive = directive_by_beat.get(beat.id)
            choreography_event_ids = (
                {flow.event_id for flow in directive.event_flows}
                if directive is not None
                else set()
            )
            for segment in cue.segments:
                if not cls._window(
                    segment.start,
                    segment.end,
                    lower=beat.start,
                    upper=beat.end,
                ):
                    cls._add(
                        violations,
                        "motion_segment_window_outside_beat",
                        beat_id=beat.id,
                        asset_id=cue.asset_id,
                        phase=segment.phase,
                        start=segment.start,
                        end=segment.end,
                        beat_start=beat.start,
                        beat_end=beat.end,
                    )
                if (
                    segment.semantic_event_id
                    and segment.semantic_event_id not in story_event_ids
                ):
                    cls._add(
                        violations,
                        "motion_segment_event_not_owned_by_story",
                        beat_id=beat.id,
                        asset_id=cue.asset_id,
                        phase=segment.phase,
                        event_id=segment.semantic_event_id,
                    )
                if (
                    segment.semantic_event_id
                    and segment.semantic_event_id not in choreography_event_ids
                ):
                    cls._add(
                        violations,
                        "motion_segment_event_not_owned_by_choreography",
                        beat_id=beat.id,
                        asset_id=cue.asset_id,
                        phase=segment.phase,
                        event_id=segment.semantic_event_id,
                    )
                for field_name, participant_asset_id in (
                    ("source", segment.source_asset_id),
                    ("target", segment.target_asset_id),
                    ("result", segment.result_asset_id),
                ):
                    if not participant_asset_id:
                        continue
                    cls._require_asset_scene(
                        violations,
                        asset_by_id=asset_by_id,
                        asset_id=participant_asset_id,
                        scene_id=beat.scene_id,
                        kind=f"motion_segment_{field_name}_reference",
                        beat_id=beat.id,
                        cue_asset_id=cue.asset_id,
                        phase=segment.phase,
                    )
                    if participant_asset_id not in layout_ids:
                        cls._add(
                            violations,
                            "motion_segment_asset_missing_from_composition",
                            beat_id=beat.id,
                            cue_asset_id=cue.asset_id,
                            phase=segment.phase,
                            role=field_name,
                            asset_id=participant_asset_id,
                        )
                if (
                    segment.handoff_deadline is not None
                    and segment.end > segment.handoff_deadline + _EPS
                ):
                    cls._add(
                        violations,
                        "motion_segment_past_handoff_deadline",
                        beat_id=beat.id,
                        asset_id=cue.asset_id,
                        phase=segment.phase,
                        end=segment.end,
                        handoff_deadline=segment.handoff_deadline,
                    )
                cls._validate_segment_program(
                    violations,
                    beat_id=beat.id,
                    asset_id=cue.asset_id,
                    phase=segment.phase,
                    program=segment.program,
                )
                if (
                    segment.phase == "ENTRY"
                    and layout_item is not None
                    and not geometry_locked
                ):
                    cls._validate_entry_renderability(
                        violations,
                        beat_id=beat.id,
                        asset_id=cue.asset_id,
                        item=layout_item,
                        duration=max(0.0, float(segment.end) - float(segment.start)),
                        program=segment.program,
                        kind="motion_segment_entry_render_dead_zone",
                    )

        for beat in story:
            layout = layout_by_beat.get(beat.id)
            layout_ids = {item.asset_id for item in layout.items} if layout else set()
            required = {
                asset_id
                for asset_id in layout_ids
                if (asset := asset_by_id.get(asset_id)) is not None
                and asset.can_animate_independently
            }
            actual = cues_by_beat.get(beat.id, set())
            missing = sorted(required - actual)
            foreign = sorted(actual - layout_ids)
            if missing or foreign:
                cls._add(
                    violations,
                    "motion_does_not_cover_composition",
                    beat_id=beat.id,
                    missing=missing,
                    foreign=foreign,
                )

        cls._raise(
            "motion->text/render",
            "MOTION_HANDOFF_CONTRACT_VIOLATIONS",
            violations,
        )

    @classmethod
    def _validate_entry_renderability(
        cls,
        violations: list[dict[str, object]],
        *,
        beat_id: str,
        asset_id: str,
        item,
        duration: float,
        program: dict,
        kind: str,
    ) -> None:
        """Require final ENTRY to be exactly static or encoded-readable.

        Pass2 provenance, attention damping, density budgets, and reference enforcement
        may all reshape a cue before Render. The final handoff is therefore the last
        owner-neutral place to prohibit non-zero sub-floor motion.
        """
        name = str(program.get("name") or "")
        if "compound_unit" in name or bool(program.get("collision_limited")):
            return
        keyframes = program.get("keyframes")
        if not isinstance(keyframes, list) or len(keyframes) < 2:
            return
        floor_px = semantic_readability_floor_px(
            "ENTRY",
            item_width=float(item.width),
            item_height=float(item.height),
            duration=max(1e-6, float(duration)),
        )
        activity_px = 0.0
        for frame in keyframes:
            if not isinstance(frame, dict):
                continue
            try:
                activity_px = max(
                    activity_px,
                    projected_motion_activity_px(
                        dx=float(frame.get("dx", 0.0)),
                        dy=float(frame.get("dy", 0.0)),
                        scale=float(frame.get("scale", 1.0)),
                        item_width=float(item.width),
                        item_height=float(item.height),
                    ),
                )
            except (TypeError, ValueError, OverflowError):
                return
        if 1e-6 < activity_px + 1e-12 < floor_px - 1e-6:
            cls._add(
                violations,
                kind,
                beat_id=beat_id,
                asset_id=asset_id,
                expected_px=activity_px,
                readability_floor_px=floor_px,
                duration=duration,
            )

