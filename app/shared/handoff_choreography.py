from __future__ import annotations

from math import isfinite

from app.choreography import ChoreographyPlan
from app.models import CompositionBeat, StoryBeat, VisualAsset

from .handoff_core import _EPS, _HandoffCore


class ChoreographyCompositionHandoffMixin(_HandoffCore):
    @classmethod
    def require_choreography_for_composition(
        cls,
        *,
        story: list[StoryBeat],
        assets: list[VisualAsset],
        choreography: ChoreographyPlan,
    ) -> None:
        violations: list[dict[str, object]] = []
        beat_by_id = {beat.id: beat for beat in story}
        asset_by_id = {asset.id: asset for asset in assets}
        expected_order = [beat.id for beat in story]
        actual_order = [directive.beat_id for directive in choreography.directives]
        if actual_order != expected_order:
            cls._add(
                violations,
                "directive_order_does_not_match_story",
                expected=expected_order,
                actual=actual_order,
            )
        cls._duplicates(
            (sequence.id for sequence in choreography.sequences),
            kind="duplicate_choreography_sequence_id",
            field="sequence_id",
            violations=violations,
        )
        sequence_beat_order = [
            beat_id
            for sequence in choreography.sequences
            for beat_id in sequence.beat_ids
        ]
        if sequence_beat_order != expected_order:
            cls._add(
                violations,
                "sequence_coverage_does_not_match_story",
                expected=expected_order,
                actual=sequence_beat_order,
            )
        sequence_ids = {sequence.id for sequence in choreography.sequences}
        sequence_membership = {
            (sequence.id, beat_id)
            for sequence in choreography.sequences
            for beat_id in sequence.beat_ids
        }

        for directive in choreography.directives:
            beat = beat_by_id.get(directive.beat_id)
            if beat is None:
                cls._add(
                    violations,
                    "directive_unknown_beat",
                    beat_id=directive.beat_id,
                )
                continue
            if directive.sequence_id not in sequence_ids:
                cls._add(
                    violations,
                    "directive_unknown_sequence",
                    beat_id=beat.id,
                    sequence_id=directive.sequence_id,
                )
            elif (directive.sequence_id, beat.id) not in sequence_membership:
                cls._add(
                    violations,
                    "directive_beat_missing_from_sequence",
                    beat_id=beat.id,
                    sequence_id=directive.sequence_id,
                )
            story_event_ids = {
                activation.semantic_event_id
                for activation in beat.asset_activations
                if activation.semantic_event_id
            }
            story_event_ids.update(
                proxy.semantic_event_id for proxy in beat.semantic_event_proxies
            )
            flow_ids = {flow.event_id for flow in directive.event_flows}
            cls._duplicates(
                (flow.event_id for flow in directive.event_flows),
                kind="duplicate_choreography_event_flow",
                field="event_id",
                violations=violations,
                context={"beat_id": beat.id},
            )

            refs = cls._directive_asset_refs(directive)
            for asset_id in refs:
                cls._require_asset_scene(
                    violations,
                    asset_by_id=asset_by_id,
                    asset_id=asset_id,
                    scene_id=beat.scene_id,
                    kind="choreography_asset_reference",
                    beat_id=beat.id,
                )

            for flow in directive.event_flows:
                if flow.event_id not in story_event_ids:
                    cls._add(
                        violations,
                        "choreography_event_not_owned_by_story",
                        beat_id=beat.id,
                        event_id=flow.event_id,
                    )
                for dependency_id in flow.dependency_ids:
                    if dependency_id not in flow_ids:
                        cls._add(
                            violations,
                            "choreography_dependency_missing_from_beat",
                            beat_id=beat.id,
                            event_id=flow.event_id,
                            dependency_id=dependency_id,
                        )
                target_ids = flow.handoff_to_event_ids or (
                    (flow.handoff_to_event_id,) if flow.handoff_to_event_id else ()
                )
                for target_id in target_ids:
                    if target_id not in flow_ids:
                        cls._add(
                            violations,
                            "choreography_handoff_target_missing_from_beat",
                            beat_id=beat.id,
                            event_id=flow.event_id,
                            target_event_id=target_id,
                        )
                for step in flow.steps:
                    if (step.spoken_start is None) != (step.spoken_end is None):
                        cls._add(
                            violations,
                            "partial_choreography_step_window",
                            beat_id=beat.id,
                            event_id=flow.event_id,
                            stage=step.stage.value,
                        )
                    elif step.spoken_start is not None and step.spoken_end is not None:
                        if not cls._window(
                            step.spoken_start,
                            step.spoken_end,
                            lower=beat.start,
                            upper=beat.end,
                        ):
                            cls._add(
                                violations,
                                "choreography_step_window_outside_beat",
                                beat_id=beat.id,
                                event_id=flow.event_id,
                                stage=step.stage.value,
                                spoken_start=step.spoken_start,
                                spoken_end=step.spoken_end,
                                beat_start=beat.start,
                                beat_end=beat.end,
                            )

        for sequence in choreography.sequences:
            if any(beat_id not in beat_by_id for beat_id in sequence.beat_ids):
                cls._add(
                    violations,
                    "sequence_unknown_beat",
                    sequence_id=sequence.id,
                    beat_ids=list(sequence.beat_ids),
                )
                continue
            if not (
                isfinite(sequence.start)
                and isfinite(sequence.end)
                and sequence.start < sequence.end
            ):
                cls._add(
                    violations,
                    "invalid_choreography_sequence_window",
                    sequence_id=sequence.id,
                    start=sequence.start,
                    end=sequence.end,
                )
                continue
            first = beat_by_id[sequence.beat_ids[0]]
            last = beat_by_id[sequence.beat_ids[-1]]
            if sequence.start < first.start - _EPS or sequence.end > last.end + _EPS:
                cls._add(
                    violations,
                    "sequence_window_outside_story",
                    sequence_id=sequence.id,
                    start=sequence.start,
                    end=sequence.end,
                    story_start=first.start,
                    story_end=last.end,
                )

        cls._raise(
            "choreography->composition",
            "CHOREOGRAPHY_HANDOFF_CONTRACT_VIOLATIONS",
            violations,
        )

    @classmethod
    def require_composition_for_motion(
        cls,
        *,
        story: list[StoryBeat],
        assets: list[VisualAsset],
        composition: list[CompositionBeat],
    ) -> None:
        violations: list[dict[str, object]] = []
        beat_by_id = {beat.id: beat for beat in story}
        asset_by_id = {asset.id: asset for asset in assets}
        expected_order = [beat.id for beat in story]
        actual_order = [layout.beat_id for layout in composition]
        if actual_order != expected_order:
            cls._add(
                violations,
                "composition_order_does_not_match_story",
                expected=expected_order,
                actual=actual_order,
            )
        cls._duplicates(
            actual_order,
            kind="duplicate_composition_beat",
            field="beat_id",
            violations=violations,
        )

        for layout in composition:
            beat = beat_by_id.get(layout.beat_id)
            if beat is None:
                cls._add(
                    violations,
                    "composition_unknown_beat",
                    beat_id=layout.beat_id,
                )
                continue
            cls._duplicates(
                (item.asset_id for item in layout.items),
                kind="duplicate_composition_asset",
                field="asset_id",
                violations=violations,
                context={"beat_id": beat.id},
            )
            layout_ids = {item.asset_id for item in layout.items}
            required_independent = {
                asset.id
                for asset in assets
                if asset.scene_id == beat.scene_id and asset.can_animate_independently
            }
            missing_independent = sorted(required_independent - layout_ids)
            if missing_independent:
                cls._add(
                    violations,
                    "composition_missing_independent_assets",
                    beat_id=beat.id,
                    asset_ids=missing_independent,
                )
            for item in layout.items:
                cls._require_asset_scene(
                    violations,
                    asset_by_id=asset_by_id,
                    asset_id=item.asset_id,
                    scene_id=beat.scene_id,
                    kind="composition_asset_reference",
                    beat_id=beat.id,
                )
                values = (item.x, item.y, item.width, item.height)
                if not all(isfinite(value) for value in values):
                    cls._add(
                        violations,
                        "nonfinite_composition_geometry",
                        beat_id=beat.id,
                        asset_id=item.asset_id,
                    )
                elif item.width <= 0.0 or item.height <= 0.0:
                    cls._add(
                        violations,
                        "nonpositive_composition_geometry",
                        beat_id=beat.id,
                        asset_id=item.asset_id,
                        width=item.width,
                        height=item.height,
                    )

        cls._raise(
            "composition->motion",
            "COMPOSITION_HANDOFF_CONTRACT_VIOLATIONS",
            violations,
        )

