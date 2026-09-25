from __future__ import annotations

from math import hypot

from app.choreography import ChoreographyPattern, ChoreographyPlan, EventFlowStage, HookKind
from app.models import AssetActivation, CompositionBeat, LayoutItem, MotionCue, MotionSegment, StoryBeat, VisualAsset
from app.motion.compiler import MotionCompiler
from app.motion.event_flow import MotionEventAssignment, MotionEventFlowResolver, MotionEventPhase
from app.motion.models import MotionKeyframe, MotionProgram
from app.motion.order import MotionOrderResolver
from app.motion.semantic_primitives import SemanticMotionPrimitiveLibrary
from app.motion.style import MotionStyleDirector
from app.motion.timing import MotionTimingPolicy, story_activation_window


class MotionPlanner:
    """Compile Choreography intent into backend-neutral motion programs.

    Composition owns semantic resting positions. Choreography owns what happens. Motion
    owns the trajectory/pacing between those states. The fallback style director remains
    only for callers that do not yet provide a ChoreographyPlan.
    """

    def __init__(self) -> None:
        self.primitives = SemanticMotionPrimitiveLibrary()
        self.timing = MotionTimingPolicy()
        self.style = MotionStyleDirector()
        self.ordering = MotionOrderResolver()
        self.compiler = MotionCompiler()
        self.event_flow = MotionEventFlowResolver()

    def plan(
        self,
        beats: list[StoryBeat],
        composition: list[CompositionBeat],
        choreography: ChoreographyPlan | None = None,
        assets: list[VisualAsset] | None = None,
    ) -> list[MotionCue]:
        by_beat = {item.beat_id: item for item in composition}
        by_asset = {asset.id: asset for asset in assets or []}
        cues: list[MotionCue] = []
        previous_pace_tier: str | None = None
        last_attention_reset = 0.0
        previous_layout: CompositionBeat | None = None

        for beat_index, beat in enumerate(beats):
            layout = by_beat.get(beat.id)
            if layout is None or not layout.items:
                continue
            directive = choreography.for_beat(beat.id) if choreography else None
            activation_by_asset = {
                row.asset_id: row for row in beat.asset_activations
            }
            ordered_slots = self.ordering.resolve(
                beat=beat,
                items=layout.items,
                assets_by_id=by_asset,
            )
            ordered_items = [slot.item for slot in ordered_slots]
            items_by_id = {row.asset_id: row for row in ordered_items}
            if directive is None and choreography is None:
                visual_duration = max(0.08, beat.end - beat.start)
                count = len(ordered_slots)
                for index, slot in enumerate(ordered_slots):
                    item = slot.item
                    asset = by_asset.get(item.asset_id)
                    activation = activation_by_asset.get(item.asset_id)
                    family_secondary = self._is_family_secondary(asset)
                    program = (
                        self.primitives.build_family_secondary()
                        if family_secondary
                        else self.primitives.build_legacy(
                            action=beat.action, item=item, index=index, count=count,
                            visual_duration=visual_duration,
                        )
                    )
                    program = self._stable_entry_hold(program)
                    window = self.timing.legacy_window(
                        beat=beat,
                        distance=program.travel_distance,
                        index=index,
                        count=count,
                        primary=(
                            item.asset_id in beat.primary_asset_ids
                            or (not beat.primary_asset_ids and index == 0)
                        ),
                        activation=activation,
                        settle_progress=program.settle_progress,
                        visual_unit_index=slot.internal_index,
                        visual_unit_count=slot.internal_count,
                    )
                    cues.append(self.compiler.compile(
                        beat=beat, asset_id=item.asset_id, program=program, window=window,
                        index=index, count=count, hook=False, handoff=bool(beat.handoff_from),
                        attention_reset=False, variant=0, intensity=1.0, choreography=None,
                        motion_order=slot.to_payload(),
                        render_constraints=(
                            {"geometry_lock": "authored_footprint", "reveal_mode": "alpha_only"}
                            if family_secondary else None
                        ),
                    ))
                continue

            pace_tier = self.timing.pace_tier_for_beat(
                beat,
                choreography_action=directive.action if directive else None,
                pacing_bias=directive.pacing_bias if directive else 1.0,
            )

            if directive is not None:
                pattern = directive.pattern
                hook = directive.hook != HookKind.NONE
                attention_reset = directive.hook == HookKind.REHOOK
                variant = beat_index % 4
                intensity = directive.energy
                action = directive.interaction.semantic_action if directive.interaction is not None else directive.action
                phase = directive.phase.value
                tension = directive.tension
                hook_kind = directive.hook.value
                hook_mechanism = directive.hook_mechanism.value
            else:
                pattern = ChoreographyPattern.STANDARD
                style = self.style.decide(
                    beat=beat,
                    beat_index=beat_index,
                    pace_tier=pace_tier,
                    previous_pace_tier=previous_pace_tier,
                    last_attention_reset=last_attention_reset,
                )
                hook = style.hook
                attention_reset = style.attention_reset
                variant = style.variant
                intensity = style.intensity
                action = beat.action
                phase = "ACTION"
                tension = 0.0
                hook_kind = "OPEN" if style.hook else "REHOOK" if style.attention_reset else "NONE"
                hook_mechanism = "CURIOSITY" if style.hook else "ESCALATION" if style.attention_reset else "NONE"

            audio_start = beat.audio_start if beat.audio_start is not None else beat.start
            if hook or attention_reset:
                last_attention_reset = audio_start
            previous_pace_tier = pace_tier

            visual_duration = max(0.08, beat.end - beat.start)
            count = len(ordered_slots)
            preferred_primary_id = directive.primary_asset_id if directive is not None else None
            preferred_interaction_id = directive.interaction_asset_id if directive is not None else None
            primary_item = self._primary_item(
                beat,
                ordered_items,
                preferred_asset_id=preferred_primary_id,
            )
            target_item = self._target_item(
                beat,
                ordered_items,
                primary_item,
                preferred_asset_id=preferred_interaction_id,
            )
            previous_items = {item.asset_id: item for item in previous_layout.items} if previous_layout else {}
            participant_roles = {
                slot.item.asset_id: (
                    directive.participant_role(slot.item.asset_id).value
                    if directive is not None
                    else "SUPPORT"
                )
                for slot in ordered_slots
            }
            semantic_unit_member_counts: dict[str, int] = {}
            for activation in beat.asset_activations:
                if activation.semantic_unit_id:
                    semantic_unit_member_counts[activation.semantic_unit_id] = (
                        semantic_unit_member_counts.get(activation.semantic_unit_id, 0) + 1
                    )
            event_assignments = self.event_flow.resolve_all(
                directive,
                [slot.item.asset_id for slot in ordered_slots],
                semantic_event_by_asset={
                    asset_id: activation.semantic_event_id
                    for asset_id, activation in activation_by_asset.items()
                },
            )
            attention_profiles = {}
            for slot in ordered_slots:
                asset_id = slot.item.asset_id
                activation = activation_by_asset.get(asset_id)
                base_profile = self._semantic_focus_profile(
                    beat=beat,
                    activation=activation,
                    participant_role=participant_roles[asset_id],
                    static_primary=(slot.item is primary_item),
                )
                attention_profiles[asset_id] = self._event_focus_profile(
                    beat=beat,
                    activation=activation,
                    assignment=event_assignments.get(asset_id),
                    base_profile=base_profile,
                )
            cohort_budget = self._cohort_attention_budget(
                beat=beat,
                activation_by_asset=activation_by_asset,
                attention_profiles=attention_profiles,
                participant_roles=participant_roles,
                preferred_primary_id=preferred_primary_id,
                preferred_interaction_id=preferred_interaction_id,
            )

            for index, slot in enumerate(ordered_slots):
                item = slot.item
                asset = by_asset.get(item.asset_id)
                family_secondary = self._is_family_secondary(asset)
                assignment = event_assignments.get(item.asset_id)
                compound_unit_locked = self._compound_unit_motion_locked(
                    activation=activation_by_asset.get(item.asset_id),
                    semantic_unit_member_counts=semantic_unit_member_counts,
                )
                interaction_vector = self._event_interaction_vector(
                    assignment=assignment,
                    item=item,
                    items_by_id=items_by_id,
                    fallback=self._interaction_vector(
                        item=item,
                        primary_item=primary_item,
                        target_item=target_item,
                    ),
                )
                participant_role = participant_roles[item.asset_id]
                activation = activation_by_asset.get(item.asset_id)
                (
                    momentary_focus,
                    focus_role,
                    focus_source,
                    focus_strength,
                    semantic_role,
                ) = attention_profiles[item.asset_id]
                cohort_gain, cohort_role = cohort_budget.get(
                    item.asset_id,
                    (1.0, "independent"),
                )
                continuity_source = previous_items.get(item.asset_id)
                # Continuity is allowed only for the exact same visual asset. A semantic
                # handoff between unrelated illustrations must not start the new artwork
                # from the previous artwork's screen position; that was the source of
                # large cross-screen sweeps on dense/new Final Packages.
                if family_secondary:
                    program = self.primitives.build_family_secondary()
                elif compound_unit_locked:
                    program = self._compound_unit_program()
                elif continuity_source is not None:
                    source = continuity_source
                    previous_offset = (source.x - item.x, source.y - item.y)
                    width_ratio = source.width / max(item.width, 1e-6)
                    height_ratio = source.height / max(item.height, 1e-6)
                    previous_scale = max(0.82, min(1.18, (width_ratio + height_ratio) / 2.0))
                    program = self.primitives.build_continuity(
                        action=action,
                        item=item,
                        index=index,
                        count=count,
                        visual_duration=visual_duration,
                        previous_offset=previous_offset,
                        previous_scale=previous_scale,
                        interaction_vector=interaction_vector,
                        phase=phase,
                        hook_kind=hook_kind,
                        hook_mechanism=hook_mechanism,
                        energy=intensity,
                        tension=tension,
                        variant=variant + index,
                        same_asset=True,
                        is_primary=item is primary_item,
                        participant_role=participant_role,
                    )
                else:
                    program = self.primitives.build(
                        action=action,
                        item=item,
                        index=index,
                        count=count,
                        visual_duration=visual_duration,
                        interaction_vector=interaction_vector,
                        phase=phase,
                        hook_kind=hook_kind,
                        hook_mechanism=hook_mechanism,
                        energy=intensity,
                        tension=tension,
                        variant=variant + index,
                        is_primary=item is primary_item,
                        participant_role=participant_role,
                    )
                program = self._stable_entry_hold(program)
                program = self._apply_attention_budget(
                    program,
                    focus_strength=focus_strength,
                    focus_role=focus_role,
                    momentary_focus=momentary_focus,
                    primary=(item is primary_item),
                    cohort_gain=cohort_gain,
                )
                entry_program = program
                state_target = bool(
                    directive is not None
                    and any(
                        row.asset_id == item.asset_id and row.meaningful
                        for row in directive.state_transitions
                    )
                )
                explicit_event_timeline = bool(
                    assignment is not None
                    and self._has_explicit_event_timeline(assignment, activation)
                )
                if not family_secondary and not compound_unit_locked:
                    if assignment is not None:
                        has_story_window, event_story_window = story_activation_window(activation, beat)
                        active_seconds = (
                            max(0.0, event_story_window.settle_at - event_story_window.reveal_start)
                            if has_story_window and event_story_window is not None
                            else 0.0
                        )
                        program = self._apply_event_flow_motion(
                            program,
                            assignment=assignment,
                            item=item,
                            items_by_id=items_by_id,
                            fallback_vector=interaction_vector,
                            active_seconds=active_seconds,
                            focus_strength=focus_strength,
                            energy=intensity,
                            cohort_gain=cohort_gain,
                        )
                    else:
                        program = self._apply_choreography_pattern(
                            program,
                            pattern=pattern,
                            participant_role=participant_role,
                            primary=(item is primary_item),
                            momentary_focus=momentary_focus,
                            focus_role=focus_role,
                            focus_strength=focus_strength,
                            state_target=state_target,
                            interaction_vector=interaction_vector,
                            energy=intensity,
                            cohort_gain=cohort_gain,
                        )
                program = self._apply_density_budget(
                    program,
                    count=count,
                    primary=(item is primary_item or momentary_focus),
                    focus_role=focus_role,
                    geometry_locked=family_secondary,
                )

                # Choreography may promote a semantic support cutout (for example a card,
                # wallet, or limit badge) to visual focus while Story keeps the authored
                # scene-primary artwork for continuity/QA. Both need to be readable at the
                # narration anchor: only the choreography focus receives the primary
                # semantic gesture, but every Story-primary asset uses the primary timing
                # contract so it cannot arrive late behind the spoken idea.
                timing_primary = (
                    item is primary_item
                    or momentary_focus
                    or item.asset_id in beat.primary_asset_ids
                )
                window = self.timing.window(
                    beat=beat,
                    distance=program.travel_distance,
                    index=index,
                    count=count,
                    primary=timing_primary,
                    settle_progress=program.settle_progress,
                    hook=hook,
                    pace_tier=pace_tier,
                    activation=activation,
                    visual_unit_index=slot.internal_index,
                    visual_unit_count=slot.internal_count,
                )
                cues.append(
                    self.compiler.compile(
                        beat=beat,
                        asset_id=item.asset_id,
                        program=program,
                        window=window,
                        index=index,
                        count=count,
                        hook=hook,
                        handoff=bool(beat.handoff_from),
                        attention_reset=attention_reset,
                        variant=variant,
                        intensity=intensity,
                        semantic_focus={
                            "active": momentary_focus,
                            "role": focus_role,
                            "source": focus_source,
                            "strength": round(focus_strength, 4),
                            "cohort_gain": round(cohort_gain, 4),
                            "cohort_role": cohort_role,
                            "semantic_role": semantic_role,
                            "focus_duration_ms": round(
                                max(0.0, window.semantic_settle - window.start) * 1000
                            ),
                            "attention_decay": "static_hold",
                            "handoff_residual_strength": 0.40,
                            "visual_focus": (
                                str(activation.visual_focus).upper()
                                if activation is not None and activation.visual_focus
                                else None
                            ),
                            "semantic_event_id": (
                                activation.semantic_event_id if activation is not None else None
                            ),
                            "semantic_event_order": (
                                activation.semantic_event_order if activation is not None else None
                            ),
                            "semantic_event_roles": (
                                list(activation.semantic_event_roles) if activation is not None else []
                            ),
                            "semantic_event_dependency_ids": (
                                list(activation.semantic_event_dependency_ids)
                                if activation is not None
                                else []
                            ),
                            "event_flow": (
                                assignment.to_payload() if assignment is not None else None
                            ),
                            "event_flow_execution": (
                                "COMPOUND_UNIT_LOCK"
                                if compound_unit_locked
                                else "EXECUTED" if assignment is not None else "NONE"
                            ),
                            "compound_visual_classification": (
                                activation.compound_visual_classification
                                if activation is not None else None
                            ),
                            "trigger_char_start": (
                                activation.trigger_char_start if activation is not None else None
                            ),
                            "trigger_char_end": (
                                activation.trigger_char_end if activation is not None else None
                            ),
                        },
                        motion_order=slot.to_payload(),
                        render_constraints=(
                            {"geometry_lock": "authored_footprint", "reveal_mode": "alpha_only"}
                            if family_secondary else None
                        ),
                        choreography=(
                            {
                                "sequence_id": directive.sequence_id,
                                "phase": directive.phase.value,
                                "action": directive.action,
                                "pattern": directive.pattern.value,
                                "hook": directive.hook.value,
                                "hook_mechanism": directive.hook_mechanism.value,
                                "tension": directive.tension,
                                "relationship": directive.relationship,
                                "primary_asset_id": directive.primary_asset_id,
                                "interaction_asset_id": directive.interaction_asset_id,
                                "actor_asset_ids": list(directive.actor_asset_ids),
                                "continuity_from": directive.continuity_from,
                                "continuity_mode": directive.continuity_mode.value,
                                "participant_role": participant_role,
                                "semantic_unit_ids": list(directive.semantic_unit_ids),
                                "state_transitions": [
                                    {
                                        "asset_id": row.asset_id,
                                        "from": row.from_state,
                                        "to": row.to_state,
                                        "reason": row.reason,
                                        "semantic_unit_id": row.semantic_unit_id,
                                        "confidence": row.confidence,
                                        "meaningful": row.meaningful,
                                    }
                                    for row in directive.state_transitions
                                ],
                                "interaction": (
                                    {
                                        "semantic_action": directive.interaction.semantic_action,
                                        "relationship": directive.interaction.relationship,
                                        "subject_asset_id": directive.interaction.subject_asset_id,
                                        "object_asset_id": directive.interaction.object_asset_id,
                                        "result_asset_id": directive.interaction.result_asset_id,
                                        "authority": directive.interaction.authority,
                                        "confidence": directive.interaction.confidence,
                                        "executable": directive.interaction.executable,
                                    }
                                    if directive.interaction is not None
                                    else None
                                ),
                                "interactions": [
                                    {
                                        "semantic_action": row.semantic_action,
                                        "relationship": row.relationship,
                                        "subject_asset_id": row.subject_asset_id,
                                        "object_asset_id": row.object_asset_id,
                                        "result_asset_id": row.result_asset_id,
                                        "subject_unit_id": row.subject_unit_id,
                                        "object_unit_id": row.object_unit_id,
                                        "result_unit_id": row.result_unit_id,
                                        "authority": row.authority,
                                        "confidence": row.confidence,
                                        "executable": row.executable,
                                    }
                                    for row in directive.interactions
                                ],
                                "package_evidence": list(directive.package_evidence),
                                "grammar_stages": [stage.value for stage in directive.grammar_stages],
                                "asset_requirements": [
                                    {
                                        "semantic_unit_id": row.semantic_unit_id,
                                        "participant_role": row.participant_role.value,
                                        "required_for_action": row.required_for_action,
                                        "satisfied": row.satisfied,
                                        "bound_asset_id": row.bound_asset_id,
                                    }
                                    for row in directive.asset_requirements
                                ],
                                "event_focus_path_asset_ids": list(
                                    directive.event_focus_path_asset_ids
                                ),
                                "event_flow_assignment": (
                                    assignment.to_payload() if assignment is not None else None
                                ),
                            }
                            if directive is not None
                            else None
                        ),
                    )
                )
                if explicit_event_timeline and assignment is not None:
                    cues[-1] = self._attach_event_timeline(
                        cue=cues[-1],
                        entry_program=entry_program,
                        beat=beat,
                        assignment=assignment,
                        activation=activation,
                        item=item,
                        items_by_id=items_by_id,
                        fallback_vector=interaction_vector,
                        focus_strength=focus_strength,
                        energy=intensity,
                        cohort_gain=cohort_gain,
                        directive=directive,
                    )
            previous_layout = layout
        return cues

    @staticmethod
    def _has_explicit_event_timeline(
        assignment: MotionEventAssignment,
        activation: AssetActivation | None,
    ) -> bool:
        for phase in assignment.phase_chain:
            if (
                phase.stage in {EventFlowStage.INTERACT, EventFlowStage.REACT}
                and phase.spoken_start is not None
                and phase.spoken_end is not None
            ):
                return True
            if phase.stage == EventFlowStage.PAYOFF and (
                (phase.spoken_start is not None and phase.spoken_end is not None)
                or (activation is not None and activation.spoken_start is not None)
            ):
                return True
        return bool(assignment.handoff_to_event_ids or assignment.handoff_to_event_id)

    @classmethod
    def _attach_event_timeline(
        cls,
        *,
        cue: MotionCue,
        entry_program: MotionProgram,
        beat: StoryBeat,
        assignment: MotionEventAssignment,
        activation: AssetActivation | None,
        item: LayoutItem,
        items_by_id: dict[str, LayoutItem],
        fallback_vector: tuple[float, float],
        focus_strength: float,
        energy: float,
        cohort_gain: float,
        directive,
    ) -> MotionCue:
        """Attach later semantic actions while keeping one backward-compatible cue."""
        deadline = cls._event_handoff_deadline(
            beat=beat, assignment=assignment, directive=directive
        )
        segments: list[MotionSegment] = []
        entry_segment = cls._entry_segment_before_handoff(
            cue=cue,
            entry_program=entry_program,
            assignment=assignment,
            deadline=deadline,
            item=item,
        )
        if entry_segment is not None:
            segments.append(entry_segment)

        phases = list(assignment.phase_chain)
        react_keys = {
            (phase.event_id, phase.target_asset_id)
            for phase in phases
            if phase.stage == EventFlowStage.REACT
        }
        phases = [
            phase for phase in phases
            if not (
                phase.stage == EventFlowStage.INTERACT
                and phase.involvement == "TARGET"
                and (phase.event_id, phase.target_asset_id) in react_keys
            )
        ]
        seen: set[tuple[str, int, str, str]] = set()
        for phase in phases:
            if phase.stage not in {
                EventFlowStage.INTERACT, EventFlowStage.REACT, EventFlowStage.PAYOFF
            }:
                continue
            key = (phase.event_id, phase.step_index, phase.stage.value, phase.involvement)
            if key in seen:
                continue
            seen.add(key)
            window = cls._event_segment_window(
                phase=phase,
                activation=activation,
                cue=cue,
                beat=beat,
                deadline=deadline,
            )
            if window is None:
                continue
            vector = cls._phase_interaction_vector(
                phase=phase,
                incoming_from_asset_id=assignment.incoming_from_asset_id,
                item=item,
                items_by_id=items_by_id,
                fallback=fallback_vector,
            )
            program = cls._event_segment_program(
                phase=phase,
                vector=vector,
                item=item,
                focus_strength=focus_strength,
                energy=energy,
                cohort_gain=cohort_gain,
            )
            segments.append(
                MotionSegment(
                    phase=phase.stage.value,
                    start=window[0],
                    end=window[1],
                    program=program.to_payload(),
                    semantic_event_id=phase.event_id,
                    semantic_action=phase.semantic_action,
                    relationship=phase.relationship,
                    involvement=phase.involvement,
                    source_asset_id=phase.source_asset_id,
                    target_asset_id=phase.target_asset_id,
                    result_asset_id=phase.result_asset_id,
                    handoff_deadline=deadline,
                )
            )

        exit_segment = cls._exit_segment_before_handoff(
            cue=cue,
            assignment=assignment,
            deadline=deadline,
            item=item,
            items_by_id=items_by_id,
            existing_segments=segments,
        )
        if exit_segment is not None:
            segments.append(exit_segment)
        return cue.model_copy(update={"segments": segments})


    @classmethod
    def _entry_segment_before_handoff(
        cls,
        *,
        cue: MotionCue,
        entry_program: MotionProgram,
        assignment: MotionEventAssignment,
        deadline: float,
        item: LayoutItem | None = None,
    ) -> MotionSegment | None:
        """Fit ENTRY entirely before the next semantic handoff.

        Story owns reveal timing and the next semantic event owns its handoff boundary.
        If the legacy cue would cross that boundary, compress the entry window and
        reduce transform amplitude rather than letting two semantic actions fight.
        With effectively no legal entry window, snap to Composition by omitting ENTRY;
        later semantic segments still execute normally from identity.
        """
        start = float(cue.start)
        original_end = float(cue.end)
        needs_exit = bool(
            (assignment.handoff_to_event_ids or assignment.handoff_to_event_id)
            and cue.asset_id not in set(assignment.handoff_to_asset_ids)
        )
        available = float(deadline) - start
        exit_reserve = 0.18 if needs_exit and available >= 0.34 else 0.0
        end = min(original_end, float(deadline) - exit_reserve)
        if end <= start + 1e-6:
            return None

        original_duration = max(1e-6, original_end - start)
        fitted_duration = end - start
        fitted_program = cls._fit_entry_program(
            entry_program,
            original_duration=original_duration,
            fitted_duration=fitted_duration,
        )
        geometry_locked = (
            isinstance(cue.params, dict)
            and cue.params.get("render_constraints", {}).get("geometry_lock")
            == "authored_footprint"
        )
        if not geometry_locked:
            fitted_program = cls._ensure_readable_entry(
                fitted_program, item=item, duration=fitted_duration
            )
        return MotionSegment(
            phase="ENTRY",
            start=start,
            end=end,
            program=fitted_program.to_payload(),
            semantic_event_id=assignment.event_id,
            semantic_action=assignment.semantic_action,
            involvement=assignment.involvement,
            handoff_deadline=deadline,
        )

    @staticmethod
    def _fit_entry_program(
        program: MotionProgram,
        *,
        original_duration: float,
        fitted_duration: float,
    ) -> MotionProgram:
        """Reduce displacement when an entry is compressed by a semantic handoff."""
        if fitted_duration >= original_duration - 1e-6:
            return program

        ratio = max(0.0, min(1.0, fitted_duration / max(original_duration, 1e-6)))
        absolute_gain = max(0.0, min(1.0, fitted_duration / 0.18))
        gain = max(0.20, min(1.0, ratio, absolute_gain))
        keyframes = tuple(
            MotionKeyframe(
                progress=frame.progress,
                dx=frame.dx * gain,
                dy=frame.dy * gain,
                scale=1.0 + (frame.scale - 1.0) * gain,
                easing=frame.easing,
            )
            for frame in program.keyframes
        )
        return MotionProgram(
            name=f"{program.name}_handoff_fit",
            keyframes=keyframes,
            settle_progress=program.settle_progress,
        )


    @staticmethod
    def _ensure_readable_entry(
        program: MotionProgram,
        *,
        item: LayoutItem | None,
        duration: float,
    ) -> MotionProgram:
        size = min(item.width, item.height) if item is not None else 0.18
        floor = max(0.018, min(0.038, size * 0.16))
        if duration < 0.14:
            floor *= 0.72
        peak = max((hypot(frame.dx, frame.dy) for frame in program.keyframes), default=0.0)
        scale_peak = max((abs(frame.scale - 1.0) for frame in program.keyframes), default=0.0)
        gain = min(2.8, floor / peak) if 1e-6 < peak < floor else 1.0
        frames = tuple(
            MotionKeyframe(
                progress=frame.progress,
                dx=max(-0.075, min(0.075, frame.dx * gain)),
                dy=max(-0.075, min(0.075, frame.dy * gain)),
                scale=(
                    frame.scale
                    if peak > 1e-6 or scale_peak >= 0.045
                    else 1.0 + (-0.045 if frame.progress < program.settle_progress else 0.0)
                ),
                easing=frame.easing,
            )
            for frame in program.keyframes
        )
        return MotionProgram(
            name=f"{program.name}_readable",
            keyframes=frames,
            settle_progress=program.settle_progress,
        )

    @staticmethod
    def _event_segment_window(
        *,
        phase: MotionEventPhase,
        activation: AssetActivation | None,
        cue: MotionCue,
        beat: StoryBeat,
        deadline: float,
    ) -> tuple[float, float] | None:
        relation_start = phase.spoken_start
        relation_end = phase.spoken_end
        if phase.stage in {EventFlowStage.INTERACT, EventFlowStage.REACT}:
            if relation_start is None or relation_end is None or relation_end <= relation_start:
                return None
            span = relation_end - relation_start
            if phase.stage == EventFlowStage.INTERACT and phase.involvement == "SOURCE":
                start, end = relation_start, relation_start + span * 0.70
            elif phase.stage == EventFlowStage.REACT:
                start, end = relation_start + span * 0.20, relation_start + span * 0.84
            else:
                start, end = relation_start + span * 0.18, relation_start + span * 0.76
        elif phase.stage == EventFlowStage.PAYOFF:
            if relation_start is not None and relation_end is not None and relation_end > relation_start:
                span = relation_end - relation_start
                start = relation_start + span * 0.72
            elif activation is not None and activation.spoken_start is not None:
                start = float(activation.spoken_start)
                span = max(0.18, float((activation.spoken_end or start + 0.24) - start))
            else:
                return None
            if activation is not None and activation.spoken_start is not None:
                start = max(start, float(activation.spoken_start))
            end = start + max(0.18, min(0.34, span * 0.55))
        else:
            return None

        lower = max(float(cue.start), float(beat.start))
        upper = min(float(beat.end), float(deadline))
        start = max(lower, float(start))
        end = min(upper, float(end))
        if end - start < 0.06:
            return None
        return start, end

    @classmethod
    def _event_segment_program(
        cls,
        *,
        phase: MotionEventPhase,
        vector: tuple[float, float],
        item: LayoutItem,
        focus_strength: float,
        energy: float,
        cohort_gain: float,
    ) -> MotionProgram:
        dx, dy, scale = cls._phase_transform(
            phase=phase, vector=vector, focus_strength=max(0.0, min(1.0, focus_strength))
        )
        strength = max(0.30, min(1.0, energy)) * max(0.25, min(1.0, cohort_gain))
        dx = max(-0.075, min(0.075, dx * strength))
        dy = max(-0.075, min(0.075, dy * strength))
        scale = 1.0 + (scale - 1.0) * strength
        dx, dy, scale = cls._enforce_event_readability(
            phase=phase, item=item, dx=dx, dy=dy, scale=scale
        )
        return MotionProgram(
            name=(
                f"semantic_segment_{phase.stage.value.lower()}_"
                f"{str(phase.semantic_action or 'event').lower()}"
            ),
            settle_progress=1.0,
            keyframes=(
                MotionKeyframe(0.0, 0.0, 0.0, 1.0, "ease_out_cubic"),
                MotionKeyframe(0.48, dx, dy, scale, "ease_out_cubic"),
                MotionKeyframe(1.0, 0.0, 0.0, 1.0, "smoothstep"),
            ),
        )


    @staticmethod
    def _enforce_event_readability(
        *,
        phase: MotionEventPhase,
        item: LayoutItem,
        dx: float,
        dy: float,
        scale: float,
    ) -> tuple[float, float, float]:
        stage_floor = {
            EventFlowStage.INTERACT: 0.030,
            EventFlowStage.REACT: 0.026,
            EventFlowStage.PAYOFF: 0.020,
        }.get(phase.stage, 0.0)
        size_floor = min(0.042, min(item.width, item.height) * 0.14)
        floor = max(stage_floor, size_floor)
        magnitude = hypot(dx, dy)
        if floor > 0 and 1e-6 < magnitude < floor:
            gain = min(2.8, floor / magnitude)
            dx = max(-0.075, min(0.075, dx * gain))
            dy = max(-0.075, min(0.075, dy * gain))
        elif floor > 0 and magnitude <= 1e-6 and phase.stage != EventFlowStage.PAYOFF:
            dy = -floor

        if phase.stage == EventFlowStage.PAYOFF and abs(scale - 1.0) < 0.075:
            scale = 1.075 if scale >= 1.0 else 0.925
        elif phase.stage == EventFlowStage.REACT and abs(scale - 1.0) < 0.045:
            scale = 1.045
        return dx, dy, max(0.90, min(1.14, scale))

    @staticmethod
    def _exit_direction(
        *,
        item: LayoutItem,
        assignment: MotionEventAssignment,
        items_by_id: dict[str, LayoutItem],
    ) -> tuple[float, float]:
        target = next(
            (
                items_by_id[asset_id]
                for asset_id in assignment.handoff_to_asset_ids
                if asset_id in items_by_id and asset_id != item.asset_id
            ),
            None,
        )
        if target is not None:
            dx = item.x - target.x
            dy = item.y - target.y
        else:
            dx = item.x - 0.5
            dy = item.y - 0.5
        length = hypot(dx, dy)
        if length < 1e-5:
            dx, dy, length = 0.0, -1.0, 1.0
        magnitude = max(0.042, min(0.068, min(item.width, item.height) * 0.30))
        return dx / length * magnitude, dy / length * magnitude

    @classmethod
    def _exit_segment_before_handoff(
        cls,
        *,
        cue: MotionCue,
        assignment: MotionEventAssignment,
        deadline: float,
        item: LayoutItem,
        items_by_id: dict[str, LayoutItem],
        existing_segments: list[MotionSegment],
    ) -> MotionSegment | None:
        has_handoff = bool(assignment.handoff_to_event_ids or assignment.handoff_to_event_id)
        if not has_handoff or cue.asset_id in set(assignment.handoff_to_asset_ids):
            return None

        end = float(deadline)
        latest = max((float(segment.end) for segment in existing_segments), default=float(cue.end))
        start = max(latest, end - 0.28, float(cue.start))
        if end - start < 0.10:
            return None

        dx, dy = cls._exit_direction(
            item=item,
            assignment=assignment,
            items_by_id=items_by_id,
        )
        program = {
            "name": "semantic_release_exit",
            "settle_progress": 1.0,
            "terminal_behavior": "LEAVE",
            "keyframes": [
                {
                    "progress": 0.0,
                    "dx": 0.0,
                    "dy": 0.0,
                    "scale": 1.0,
                    "easing": "ease_in_out_cubic",
                },
                {
                    "progress": 0.60,
                    "dx": dx * 0.62,
                    "dy": dy * 0.62,
                    "scale": 0.985,
                    "easing": "ease_in_out_cubic",
                },
                {
                    "progress": 1.0,
                    "dx": dx,
                    "dy": dy,
                    "scale": 0.955,
                    "easing": "ease_in_cubic",
                },
            ],
        }
        return MotionSegment(
            phase="EXIT",
            start=start,
            end=end,
            program=program,
            semantic_event_id=assignment.event_id,
            semantic_action="RELEASE",
            relationship=assignment.relationship,
            involvement="OUTGOING",
            source_asset_id=cue.asset_id,
            target_asset_id=assignment.handoff_to_asset_id,
            handoff_deadline=deadline,
        )

    @staticmethod
    def _event_handoff_deadline(*, beat: StoryBeat, assignment: MotionEventAssignment, directive) -> float:
        candidates = [float(beat.end)]
        target_event_ids = set(assignment.handoff_to_event_ids)
        if assignment.handoff_to_event_id:
            target_event_ids.add(assignment.handoff_to_event_id)
        for activation in beat.asset_activations:
            if activation.spoken_start is None or not activation.semantic_event_id:
                continue
            if activation.semantic_event_id in target_event_ids:
                candidates.append(float(activation.spoken_start))
            elif (
                assignment.event_order is not None
                and activation.semantic_event_order is not None
                and activation.semantic_event_order > assignment.event_order
            ):
                candidates.append(float(activation.spoken_start))
        if directive is not None and assignment.event_order is not None:
            for flow in directive.event_flows:
                if flow.order is None or flow.order <= assignment.event_order:
                    continue
                starts = [
                    float(row.spoken_start)
                    for row in beat.asset_activations
                    if row.semantic_event_id == flow.event_id and row.spoken_start is not None
                ]
                if starts:
                    candidates.append(min(starts))
        valid = [value for value in candidates if value > float(beat.start) + 1e-6]
        return min(valid) if valid else float(beat.end)

    @staticmethod
    def _compound_unit_motion_locked(
        *,
        activation: AssetActivation | None,
        semantic_unit_member_counts: dict[str, int],
    ) -> bool:
        """Protect compound semantic units from fake cutout-by-cutout choreography."""
        if activation is None or not activation.semantic_unit_id:
            return False
        if semantic_unit_member_counts.get(activation.semantic_unit_id, 0) <= 1:
            return False
        return bool(
            activation.compound_visual_classification == "COMPOUND_REQUIRED"
            or activation.internal_progression_unavailable
        )

    @staticmethod
    def _compound_unit_program() -> MotionProgram:
        """One identical, translation-only reveal for every member of a locked unit."""
        return MotionProgram(
            name="compound_unit_coherent_reveal",
            settle_progress=0.78,
            keyframes=(
                MotionKeyframe(0.0, 0.0, 0.016, 1.0, "ease_out_cubic"),
                MotionKeyframe(0.78, 0.0, 0.0, 1.0, "ease_out_cubic"),
                MotionKeyframe(1.0, 0.0, 0.0, 1.0, "smoothstep"),
            ),
        )

    @staticmethod
    def _stable_entry_hold(program: MotionProgram) -> MotionProgram:
        """Remove wobble/recoil after arrival and keep one clean entry trajectory.

        Composition owns the final authored position. Motion may reveal an asset on the
        way to that destination, but once the asset reaches settle_progress it must
        remain completely still for the rest of the beat. Keeping only the first
        transform plus the semantic settle point also removes tiny pre-settle oscillation
        authored by reaction/bounce primitives while preserving the intended entrance.
        """
        first = program.keyframes[0]
        settle = next(
            frame
            for frame in program.keyframes
            if abs(frame.progress - program.settle_progress) <= 1e-9
        )
        # Once post-arrival reactions are removed, an early settle_progress only
        # compresses the visible entrance. Reference-calibrated motion spends most
        # of the available window travelling, then freezes cleanly on the semantic
        # anchor. Keep primitives that intentionally settle at 100%, otherwise use
        # a common readable 78% entry phase.
        settle_progress = max(0.78, program.settle_progress)
        # The reference edit style uses a readable deceleration curve. Several
        # semantic primitives start with ease_out_expo/back, which front-load too
        # much distance into the first few frames once the program is reduced to
        # one clean entry. Normalize that single entry segment to cubic ease-out:
        # fast enough to feel intentional, but with a long, smooth settle.
        frames = [
            MotionKeyframe(
                0.0,
                first.dx,
                first.dy,
                first.scale,
                "ease_out_cubic",
            ),
        ]
        if settle_progress < 1.0 - 1e-9:
            frames.append(
                MotionKeyframe(
                    settle_progress,
                    0.0,
                    0.0,
                    1.0,
                    settle.easing,
                )
            )
        frames.append(MotionKeyframe(1.0, 0.0, 0.0, 1.0, "smoothstep"))
        return MotionProgram(
            name=program.name,
            keyframes=tuple(frames),
            settle_progress=settle_progress,
        )

    @staticmethod
    def _semantic_focus_profile(
        *,
        beat: StoryBeat,
        activation: AssetActivation | None,
        participant_role: str,
        static_primary: bool,
    ) -> tuple[bool, str, str, float, str]:
        """Arbitrate attention instead of promoting every timed asset equally."""
        visual_focus = (
            str(activation.visual_focus).upper()
            if activation is not None and activation.visual_focus
            else None
        )
        participant = str(participant_role or "SUPPORT").upper()
        event_roles = set(activation.semantic_event_roles) if activation is not None else set()
        semantic_role = "UNKNOWN"
        if activation is not None and activation.semantic_unit_id and beat.semantic_context:
            entity = next(
                (
                    row
                    for row in beat.semantic_context.entities
                    if row.unit_id == activation.semantic_unit_id
                ),
                None,
            )
            if entity is not None and entity.role:
                semantic_role = str(entity.role).upper()

        if "LEADER" in event_roles:
            if "RESULT" in event_roles or semantic_role == "RESULT" or visual_focus == "RESULT":
                focus_role, strength, source = "RESULT", 1.0, "semantic_event_leader"
            elif semantic_role in {"ACTION", "OBJECT", "SUBJECT", "PRIMARY", "STATE"}:
                focus_role, strength, source = semantic_role, 0.98, "semantic_event_leader"
            else:
                focus_role, strength, source = "PRIMARY", 0.98, "semantic_event_leader"
        elif "RESULT" in event_roles:
            focus_role, strength, source = "RESULT", 0.92, "semantic_event_result"
        elif "CONTEXT" in event_roles and visual_focus not in {"PRIMARY", "RESULT"}:
            return False, "CONTEXT", "semantic_event_context", 0.08, semantic_role
        elif visual_focus == "CONTEXT":
            return False, "CONTEXT", "authored_context", 0.0, semantic_role
        elif visual_focus == "RESULT":
            focus_role, strength, source = "RESULT", 1.0, "authored_visual_focus"
        elif visual_focus == "PRIMARY":
            focus_role, strength, source = "PRIMARY", 0.95, "authored_visual_focus"
        elif visual_focus == "SUPPORT":
            focus_role, strength, source = "SUPPORT", 0.30, "authored_visual_focus"
        elif participant == "RESULT":
            focus_role, strength, source = "RESULT", 0.90, "relation_result"
        elif activation is not None and activation.visual_state:
            focus_role, strength, source = "STATE", 0.88, "authored_visual_state"
        elif semantic_role == "RESULT":
            focus_role, strength, source = "RESULT", 0.82, "semantic_role"
        elif participant in {"SUBJECT", "OBJECT"}:
            focus_role, strength, source = participant, 0.74, "relation_participant"
        elif semantic_role == "PRIMARY":
            focus_role, strength, source = "PRIMARY", 0.72, "semantic_role"
        elif semantic_role == "ACTION":
            focus_role, strength, source = "ACTION", 0.68, "semantic_role"
        elif semantic_role == "OBJECT" and (
            activation is not None
            and str(activation.binding_type or "").upper() == "EXPLICIT"
        ):
            focus_role, strength, source = "OBJECT", 0.66, "explicit_semantic_object"
        elif semantic_role == "OBJECT":
            focus_role, strength, source = "SUPPORT", 0.42, "semantic_role"
        elif semantic_role == "SUPPORT":
            focus_role, strength, source = "SUPPORT", 0.28, "semantic_role"
        elif participant == "ACTOR":
            focus_role, strength, source = "ACTOR", 0.52, "actor_context"
        elif semantic_role == "CHARACTER":
            focus_role, strength, source = "CHARACTER", 0.48, "semantic_role"
        elif activation is not None and str(activation.binding_type or "").upper() == "SUPPORT":
            focus_role, strength, source = "SUPPORT", 0.28, "support_binding"
        else:
            focus_role, strength, source = "ACTIVE_FOCUS", 0.62, "ordered_semantic_step"

        if (
            activation is not None
            and str(activation.binding_type or "").upper() == "SUPPORT"
            and visual_focus is None
            and participant != "RESULT"
            and semantic_role != "RESULT"
            and not activation.visual_state
        ):
            focus_role, strength, source = (
                "SUPPORT",
                min(strength, 0.35),
                "support_binding",
            )

        if static_primary and visual_focus not in {"SUPPORT", "CONTEXT"}:
            strength = max(strength, 0.72)
            if focus_role in {"SUPPORT", "ACTIVE_FOCUS"}:
                focus_role = "PRIMARY"

        has_v2, window = story_activation_window(activation, beat)
        active = bool(
            has_v2
            and window is not None
            and window.activation_policy in {"OWN_WINDOW", "INHERITED_WINDOW"}
            and strength >= 0.60
        )
        if active:
            return True, focus_role, source, strength, semantic_role
        if static_primary:
            return False, focus_role, "beat_primary", strength, semantic_role
        return False, focus_role, source, strength, semantic_role

    @staticmethod
    def _event_focus_profile(
        *,
        beat: StoryBeat,
        activation: AssetActivation | None,
        assignment: MotionEventAssignment | None,
        base_profile: tuple[bool, str, str, float, str],
    ) -> tuple[bool, str, str, float, str]:
        """Promote the Choreography event phase that owns the current Story window.

        This does not create timing. The override is active only when Story already owns
        a trusted activation window for the asset. Event-flow semantics therefore affect
        visual emphasis without moving any cue before speech or past semantic settle.
        """
        if assignment is None or activation is None:
            return base_profile
        has_v2, window = story_activation_window(activation, beat)
        if (
            not has_v2
            or window is None
            or window.activation_policy not in {"OWN_WINDOW", "INHERITED_WINDOW"}
        ):
            return base_profile

        _active, base_role, _source, base_strength, semantic_role = base_profile
        stage = assignment.stage
        if stage == EventFlowStage.PAYOFF:
            return True, "RESULT", "event_flow_payoff", 1.0, semantic_role
        if stage == EventFlowStage.REACT:
            role = "OBJECT" if assignment.involvement in {"TARGET", "FOCUS"} else base_role
            return True, role, "event_flow_reaction", max(0.94, base_strength), semantic_role
        if stage == EventFlowStage.INTERACT:
            if assignment.involvement == "SOURCE":
                role = "SUBJECT"
            elif assignment.involvement == "TARGET":
                role = "OBJECT"
            else:
                role = base_role
            return True, role, "event_flow_interaction", max(0.92, base_strength), semantic_role
        if stage == EventFlowStage.ADD:
            role = base_role if base_role not in {"SUPPORT", "CONTEXT", "ACTIVE_FOCUS"} else "ACTION"
            return True, role, "event_flow_add", max(0.82, base_strength), semantic_role
        if stage == EventFlowStage.ESTABLISH:
            role = base_role if base_role not in {"SUPPORT", "CONTEXT", "ACTIVE_FOCUS"} else "PRIMARY"
            return True, role, "event_flow_establish", max(0.90, base_strength), semantic_role
        return base_profile

    @staticmethod
    def _phase_interaction_vector(
        *,
        phase: MotionEventPhase,
        incoming_from_asset_id: str | None,
        item: LayoutItem,
        items_by_id: dict[str, LayoutItem],
        fallback: tuple[float, float],
    ) -> tuple[float, float]:
        """Resolve one semantic phase direction from authored Composition geometry."""
        partner_id: str | None = None
        if phase.stage == EventFlowStage.INTERACT:
            if phase.involvement == "SOURCE":
                partner_id = phase.target_asset_id
            elif phase.involvement == "TARGET":
                partner_id = phase.source_asset_id
        elif phase.stage == EventFlowStage.REACT:
            partner_id = phase.source_asset_id
        elif phase.stage in {
            EventFlowStage.ESTABLISH,
            EventFlowStage.ADD,
            EventFlowStage.PAYOFF,
        }:
            partner_id = incoming_from_asset_id

        partner = items_by_id.get(partner_id) if partner_id else None
        if partner is not None:
            return (partner.x - item.x, partner.y - item.y)
        if phase.stage in {EventFlowStage.INTERACT, EventFlowStage.REACT}:
            return fallback
        # Establish/Add/Payoff without an authored previous focus should emphasize in
        # place, not inherit an unrelated generic target direction.
        return (0.0, 0.0)

    @classmethod
    def _event_interaction_vector(
        cls,
        *,
        assignment: MotionEventAssignment | None,
        item: LayoutItem,
        items_by_id: dict[str, LayoutItem],
        fallback: tuple[float, float],
    ) -> tuple[float, float]:
        if assignment is None:
            return fallback
        dominant = MotionEventPhase(
            event_id=assignment.event_id,
            event_order=assignment.event_order,
            stage=assignment.stage,
            step_index=assignment.step_index,
            involvement=assignment.involvement,
            focus_asset_id=assignment.focus_asset_id,
            source_asset_id=assignment.source_asset_id,
            target_asset_id=assignment.target_asset_id,
            result_asset_id=assignment.result_asset_id,
            relationship=assignment.relationship,
            semantic_action=assignment.semantic_action,
            authority=assignment.authority,
        )
        return cls._phase_interaction_vector(
            phase=dominant,
            incoming_from_asset_id=assignment.incoming_from_asset_id,
            item=item,
            items_by_id=items_by_id,
            fallback=fallback,
        )

    @staticmethod
    def _phase_transform(
        *,
        phase: MotionEventPhase,
        vector: tuple[float, float],
        focus_strength: float,
    ) -> tuple[float, float, float]:
        """Return one bounded relation-aware semantic accent for an event phase.

        The stage owns narrative position; semantic_action preserves the visual character
        of the authored relationship (compare, block, loop, travel, connect, etc.).
        This remains topic-agnostic and always settles back to Composition.
        """
        vx, vy = vector
        stage = phase.stage
        action = str(phase.semantic_action or "").upper()

        if stage == EventFlowStage.ESTABLISH:
            return vx * 0.035, vy * 0.035 - 0.006, 1.055 + 0.025 * focus_strength
        if stage == EventFlowStage.ADD:
            return vx * 0.075, vy * 0.075 - 0.007, 1.050 + 0.030 * focus_strength

        if stage == EventFlowStage.INTERACT:
            if action == "COMPARE":
                # Both sides move slightly away from their partner, preserving a balanced
                # contrast instead of implying subject -> target causality.
                return -vx * 0.075, -vy * 0.075 - 0.004, 1.050 + 0.020 * focus_strength
            if action == "LOOP":
                # One bounded tangential beat suggests persistence/cycle without wobble.
                return -vy * 0.12, vx * 0.12, 1.040 + 0.020 * focus_strength
            if action == "TRAVEL":
                factor = 0.18 if phase.involvement == "SOURCE" else 0.07
                return vx * factor, vy * factor, 1.045 + 0.020 * focus_strength
            if action == "CONNECT":
                factor = 0.12 if phase.involvement == "SOURCE" else 0.06
                return vx * factor, vy * factor, 1.045 + 0.020 * focus_strength
            if action in {"BLOCK", "REJECT"}:
                if phase.involvement == "TARGET":
                    return -vx * 0.050, -vy * 0.050, 1.040 + 0.015 * focus_strength
                return vx * 0.10, vy * 0.10, 1.045 + 0.020 * focus_strength
            if action == "LOCK":
                factor = 0.10 if phase.involvement == "SOURCE" else 0.07
                return vx * factor, vy * factor, 0.995 + 0.015 * focus_strength
            if action in {"PROTECT", "RESOLVE"}:
                factor = 0.08 if phase.involvement == "SOURCE" else 0.045
                return vx * factor, vy * factor, 1.045 + 0.020 * focus_strength
            if phase.involvement == "SOURCE":
                return vx * 0.14, vy * 0.14, 1.050 + 0.025 * focus_strength
            if phase.involvement == "TARGET":
                return -vx * 0.025, -vy * 0.025, 1.045 + 0.020 * focus_strength
            return 0.0, -0.006, 1.045 + 0.020 * focus_strength

        if stage == EventFlowStage.REACT:
            if action in {"BLOCK", "REJECT", "TRAVEL"}:
                return -vx * 0.070, -vy * 0.070 - 0.005, 1.065 + 0.025 * focus_strength
            if action == "LOCK":
                return vx * 0.045, vy * 0.045, 0.985 + 0.010 * focus_strength
            if action in {"CONNECT", "PROTECT", "RESOLVE"}:
                return vx * 0.050, vy * 0.050 - 0.005, 1.055 + 0.020 * focus_strength
            if action == "REVEAL":
                return 0.0, -0.010, 1.080 + 0.025 * focus_strength
            if action == "LOOP":
                return -vy * 0.085, vx * 0.085, 1.050 + 0.020 * focus_strength
            return -vx * 0.055, -vy * 0.055 - 0.006, 1.065 + 0.030 * focus_strength

        if stage == EventFlowStage.PAYOFF:
            payoff_scale = {
                "COMPARE": 1.075,
                "LOOP": 1.070,
                "BLOCK": 1.085,
                "REJECT": 1.090,
                "LOCK": 1.085,
                "TRAVEL": 1.105,
                "CONNECT": 1.110,
                "PROTECT": 1.110,
                "RESOLVE": 1.115,
                "REVEAL": 1.120,
            }.get(action, 1.105)
            return vx * 0.050, vy * 0.050 - 0.014, payoff_scale + 0.015 * focus_strength
        return 0.0, 0.0, 1.0

    @staticmethod
    def _event_phase_chain(
        assignment: MotionEventAssignment,
        active_seconds: float,
    ) -> tuple[MotionEventPhase, ...]:
        """Choose the richest readable phase chain the Story window can support.

        Reference-style movement is a semantic sequence, not continuous decoration.
        Very short narration windows therefore collapse safely to the dominant phase;
        larger windows can express an establish/add beat before interaction/reaction/payoff.
        """
        phases = list(assignment.phase_chain)
        if not phases:
            return ()

        # If the target owns a later REACT phase, its earlier INTERACT acknowledgement is
        # redundant and would read as a double reaction. Keep the source interaction.
        react_keys = {
            (phase.event_id, phase.target_asset_id)
            for phase in phases
            if phase.stage == EventFlowStage.REACT
        }
        phases = [
            phase
            for phase in phases
            if not (
                phase.stage == EventFlowStage.INTERACT
                and phase.involvement == "TARGET"
                and (phase.event_id, phase.target_asset_id) in react_keys
            )
        ]
        if not phases:
            return ()

        dominant_index = next(
            (
                index
                for index, phase in enumerate(phases)
                if phase.event_id == assignment.event_id
                and phase.step_index == assignment.step_index
                and phase.stage == assignment.stage
            ),
            len(phases) - 1,
        )
        dominant = phases[dominant_index]
        prior = phases[:dominant_index]

        if active_seconds < 0.22 or not prior:
            return (dominant,)
        if active_seconds < 0.48:
            # On compact windows, preserve the semantic beat immediately feeding the
            # dominant action/result rather than replaying an old setup beat.
            return (prior[-1], dominant)

        # Long windows may carry setup + the immediate precursor + dominant payoff.
        # This mirrors the reference grammar while avoiding decorative over-animation.
        setup = next(
            (
                phase for phase in prior
                if phase.stage in {EventFlowStage.ESTABLISH, EventFlowStage.ADD}
            ),
            prior[0],
        )
        precursor = prior[-1]
        selected = []
        for phase in (setup, precursor, dominant):
            key = (phase.event_id, phase.step_index, phase.stage, phase.involvement)
            if not any(
                (row.event_id, row.step_index, row.stage, row.involvement) == key
                for row in selected
            ):
                selected.append(phase)
        return tuple(selected)

    @classmethod
    def _apply_event_flow_motion(
        cls,
        program: MotionProgram,
        *,
        assignment: MotionEventAssignment,
        item: LayoutItem,
        items_by_id: dict[str, LayoutItem],
        fallback_vector: tuple[float, float],
        active_seconds: float,
        focus_strength: float,
        energy: float,
        cohort_gain: float = 1.0,
    ) -> MotionProgram:
        """Execute Choreography event phases as one readable pre-settle motion sentence.

        The phase chain is compressed to the available Story-owned timing. No phase can
        begin before its visual activation, continue past semantic settle, or alter final
        Composition geometry. This is intentionally one-shot; no post-settle wobble.
        """
        chain = cls._event_phase_chain(assignment, active_seconds)
        if not chain:
            return program

        first = program.keyframes[0]
        settle = max(0.78, program.settle_progress)
        focus_strength = max(0.0, min(1.0, float(focus_strength)))
        energy = max(0.35, min(1.0, float(energy)))
        gain = max(0.0, min(1.0, float(cohort_gain)))
        strength = (0.80 + energy * 0.20) * gain

        if len(chain) == 1:
            progress_points = (max(0.42, min(settle - 0.10, settle * 0.68)),)
        elif len(chain) == 2:
            progress_points = (settle * 0.36, settle * 0.72)
        else:
            progress_points = (settle * 0.26, settle * 0.50, settle * 0.76)

        frames: list[MotionKeyframe] = [
            MotionKeyframe(0.0, first.dx, first.dy, first.scale, first.easing)
        ]
        for index, (phase, progress) in enumerate(zip(chain, progress_points)):
            vector = cls._phase_interaction_vector(
                phase=phase,
                incoming_from_asset_id=assignment.incoming_from_asset_id,
                item=item,
                items_by_id=items_by_id,
                fallback=fallback_vector,
            )
            dx, dy, scale = cls._phase_transform(
                phase=phase,
                vector=vector,
                focus_strength=focus_strength,
            )
            # Earlier setup phases support the dominant semantic peak rather than
            # competing with it. This also guarantees MotionCompiler aligns Story's
            # semantic peak to the final/strongest phase in the chain.
            phase_gain = 1.0 if index == len(chain) - 1 else 0.68
            dx = max(-0.06, min(0.06, dx * strength * phase_gain))
            dy = max(-0.06, min(0.06, dy * strength * phase_gain))
            scale = 1.0 + (scale - 1.0) * strength * phase_gain
            frames.append(MotionKeyframe(
                max(0.01, min(settle - 0.02, progress)),
                dx,
                dy,
                scale,
                "ease_out_cubic",
            ))

        frames.extend((
            MotionKeyframe(settle, 0.0, 0.0, 1.0, "ease_out_cubic"),
            MotionKeyframe(1.0, 0.0, 0.0, 1.0, "smoothstep"),
        ))
        stage_name = "_".join(phase.stage.value.lower() for phase in chain)
        action_names = tuple(dict.fromkeys(
            str(phase.semantic_action).lower()
            for phase in chain
            if phase.semantic_action
        ))
        action_suffix = f"__{'_'.join(action_names)}" if action_names else ""
        return MotionProgram(
            name=f"event_chain_{stage_name}_{program.name}{action_suffix}",
            settle_progress=settle,
            keyframes=tuple(frames),
        )

    @staticmethod
    def _cohort_attention_budget(
        *,
        beat: StoryBeat,
        activation_by_asset: dict[str, AssetActivation],
        attention_profiles: dict[str, tuple[bool, str, str, float, str]],
        participant_roles: dict[str, str],
        preferred_primary_id: str | None,
        preferred_interaction_id: str | None,
    ) -> dict[str, tuple[float, str]]:
        """Bound simultaneous motion energy while preserving Story-owned timing."""
        timed: list[tuple[str, AssetActivation, object]] = []
        for asset_id, activation in activation_by_asset.items():
            has_v2, window = story_activation_window(activation, beat)
            if has_v2 and window is not None:
                timed.append((asset_id, activation, window))
        timed.sort(key=lambda row: (float(row[2].reveal_start), row[0]))

        cohorts: list[list[tuple[str, AssetActivation, object]]] = []
        threshold = 2.0 / 30.0
        for row in timed:
            if not cohorts:
                cohorts.append([row])
                continue
            anchor = cohorts[-1][0][2]
            if (
                abs(float(row[2].reveal_start) - float(anchor.reveal_start))
                <= threshold + 1e-9
                and abs(float(row[2].phrase_start) - float(anchor.phrase_start))
                <= threshold + 1e-9
            ):
                cohorts[-1].append(row)
            else:
                cohorts.append([row])

        output: dict[str, tuple[float, str]] = {}
        for cohort in cohorts:
            if len(cohort) <= 1:
                continue

            def authority(row: tuple[str, AssetActivation, object]) -> tuple[float, str]:
                asset_id, activation, _window = row
                _active, focus_role, _source, strength, semantic_role = (
                    attention_profiles[asset_id]
                )
                visual_focus = str(activation.visual_focus or "").upper()
                participant = str(participant_roles.get(asset_id, "SUPPORT")).upper()
                score = {
                    "RESULT": 100.0,
                    "PRIMARY": 96.0,
                    "ACTION": 88.0,
                    "STATE": 87.0,
                    "OBJECT": 84.0,
                    "SUBJECT": 84.0,
                    "CHARACTER": 45.0,
                    "ACTOR": 44.0,
                    "SUPPORT": 25.0,
                    "CONTEXT": 10.0,
                }.get(focus_role, 50.0)
                if visual_focus in {"RESULT", "PRIMARY"}:
                    score += 100.0
                if asset_id == preferred_primary_id:
                    score += 40.0
                if participant == "RESULT":
                    score += 35.0
                elif participant in {"SUBJECT", "OBJECT"}:
                    score += 20.0
                if semantic_role == "RESULT":
                    score += 24.0
                if asset_id in beat.primary_asset_ids:
                    score += 12.0
                return score + strength, asset_id

            explicit_leaders = [
                row for row in cohort
                if "LEADER" in row[1].semantic_event_roles
            ]
            leader_id = max(explicit_leaders or cohort, key=authority)[0]
            leader_activation = next(row[1] for row in cohort if row[0] == leader_id)
            leader_unit_id = (
                leader_activation.semantic_unit_id
                if (
                    "LEADER" in leader_activation.semantic_event_roles
                    or "visual_identity_multi_cutout_member" in leader_activation.evidence
                )
                else None
            )
            density = len(cohort)
            for asset_id, activation, _window in cohort:
                same_leader_unit = bool(
                    leader_unit_id
                    and activation.semantic_unit_id == leader_unit_id
                )
                if asset_id == leader_id or same_leader_unit:
                    output[asset_id] = (
                        1.0,
                        "leader" if asset_id == leader_id else "leader_member",
                    )
                    continue
                participant = str(participant_roles.get(asset_id, "SUPPORT")).upper()
                _active, focus_role, _source, _strength, semantic_role = (
                    attention_profiles[asset_id]
                )
                event_roles = set(activation.semantic_event_roles)
                explicit_participant = (
                    participant in {"SUBJECT", "OBJECT", "RESULT"}
                    or asset_id == preferred_interaction_id
                )
                if "CONTEXT" in event_roles:
                    gain, cohort_role = 0.18, "quiet"
                elif "RESULT" in event_roles or focus_role == "RESULT":
                    # Multiple authored results may share one semantic instant. Keep a
                    # primary result leader, but never demote sibling results to quiet.
                    gain, cohort_role = 0.80, "result_peer"
                elif explicit_participant or "PARTICIPANT" in event_roles:
                    gain, cohort_role = 0.58, "participant"
                elif focus_role in {"ACTION", "OBJECT", "SUBJECT", "STATE", "PRIMARY"}:
                    gain, cohort_role = 0.44, "secondary"
                elif semantic_role == "CHARACTER" and activation.visual_focus:
                    gain, cohort_role = 0.44, "secondary"
                else:
                    gain, cohort_role = 0.24, "quiet"
                if density >= 4 and cohort_role == "quiet":
                    gain = 0.18
                output[asset_id] = (gain, cohort_role)
        return output

    @staticmethod
    def _apply_attention_budget(
        program: MotionProgram,
        *,
        focus_strength: float,
        focus_role: str,
        momentary_focus: bool,
        primary: bool,
        cohort_gain: float = 1.0,
    ) -> MotionProgram:
        """Dampen base entry energy for non-focal context before semantic accents.

        Primitive selection can still produce a noticeable entrance even when an asset is
        intentionally not the current semantic focus. Scale the pre-settle trajectory by
        authored attention authority so a CHARACTER/SUPPORT can establish context without
        stealing the eye from the precise OBJECT/ACTION/RESULT that follows. Final geometry
        and settle timing are untouched.
        """
        role = str(focus_role or "SUPPORT").upper()
        strength = max(0.0, min(1.0, float(focus_strength)))
        if role == "CONTEXT":
            factor = 0.16
        elif role == "SUPPORT":
            factor = min(0.42, 0.18 + strength * 0.55)
        elif role in {"CHARACTER", "ACTOR"}:
            factor = min(0.58, 0.22 + strength * 0.72)
        else:
            factor = 0.22 + strength * 0.78
        if momentary_focus:
            factor = max(factor, 0.72)
        if primary and role not in {"CONTEXT", "SUPPORT", "CHARACTER", "ACTOR"}:
            factor = max(factor, 0.80)
        factor *= max(0.0, min(1.0, cohort_gain))

        frames = []
        for frame in program.keyframes:
            if frame.progress >= program.settle_progress - 1e-9:
                frames.append(frame)
                continue
            frames.append(
                MotionKeyframe(
                    frame.progress,
                    frame.dx * factor,
                    frame.dy * factor,
                    1.0 + (frame.scale - 1.0) * factor,
                    frame.easing,
                )
            )
        return MotionProgram(
            name=program.name,
            keyframes=tuple(frames),
            settle_progress=program.settle_progress,
        )

    @staticmethod
    def _apply_choreography_pattern(
        program: MotionProgram,
        *,
        pattern: ChoreographyPattern,
        participant_role: str,
        primary: bool,
        momentary_focus: bool,
        focus_role: str,
        focus_strength: float,
        state_target: bool,
        interaction_vector: tuple[float, float],
        energy: float,
        cohort_gain: float = 1.0,
    ) -> MotionProgram:
        """Add one meaning-bearing pre-settle accent without reintroducing wobble.

        The accepted stability rule remains absolute: Composition owns the destination
        and every asset is fully still from semantic settle through beat end. Stronger
        reference-style choreography therefore happens once *before* settle.
        """
        if pattern == ChoreographyPattern.STANDARD and not momentary_focus:
            return program

        first = program.keyframes[0]
        settle = max(0.78, program.settle_progress)
        accent_progress = max(0.42, min(settle - 0.10, settle * 0.67))
        role = str(participant_role or "SUPPORT").upper()
        focus_role = str(focus_role or role).upper()
        focus_strength = max(0.0, min(1.0, float(focus_strength)))
        energy = max(0.35, min(1.0, energy))
        dx = 0.0
        dy = 0.0
        scale = 1.0

        # A Story-owned activation window temporarily grants the currently spoken
        # semantic unit visual authority. This is intentionally local to the unit's
        # own cue: once it settles, it returns to authored Composition and becomes
        # completely static while the next semantic unit takes focus.
        if pattern == ChoreographyPattern.STANDARD:
            scale = 1.0 + 0.050 * focus_strength
            dy = -0.006 * focus_strength
        elif pattern == ChoreographyPattern.PROGRESSIVE_BUILD:
            if momentary_focus:
                scale = 1.0 + 0.078 * focus_strength
                dy = -0.011 * focus_strength
            elif primary:
                scale = 1.040
                dy = -0.006
            else:
                scale = 1.012
                dy = -0.002
        elif pattern == ChoreographyPattern.FOCUS_TRANSFER:
            if momentary_focus:
                scale = 1.025 + 0.070 * focus_strength
                dy = -0.012 * focus_strength
            elif primary:
                scale = 1.038
                dy = -0.005
            else:
                return program
        elif pattern == ChoreographyPattern.STATE_TRANSFORM:
            if state_target:
                scale = 1.095
                dy = -0.013
            elif momentary_focus:
                scale = 1.020 + 0.050 * focus_strength
                dy = -0.009 * focus_strength
            elif primary:
                scale = 1.030
            else:
                return program
        elif pattern == ChoreographyPattern.CAUSE_EFFECT_CHAIN:
            vx, vy = interaction_vector
            if role == "SUBJECT":
                dx = vx * 0.12
                dy = vy * 0.12
                scale = (1.026 + 0.020 * focus_strength) if momentary_focus else 1.026
            elif role == "OBJECT":
                scale = (1.045 + 0.022 * focus_strength) if momentary_focus else 1.045
                dx = -vx * 0.025
                dy = -vy * 0.025
            elif role == "RESULT" or focus_role == "RESULT":
                scale = 1.105
                dy = -0.014
            elif role == "ACTOR":
                scale = (1.025 + 0.018 * focus_strength) if momentary_focus else 1.025
                dx = vx * 0.04
                dy = vy * 0.04
            elif momentary_focus:
                scale = 1.020 + 0.045 * focus_strength
                dy = -0.009 * focus_strength
            elif primary:
                scale = 1.038
            else:
                return program

        # Calibrated attention hierarchy. These are one-shot accents only; the
        # asset returns to exact authored Composition and then stays still. ACTION is
        # decisive and short, PRIMARY/OBJECT are stronger concept anchors, and RESULT
        # receives the largest bounded payoff.
        if focus_role == "ACTION":
            scale = max(scale, 1.060)
            dy = min(dy, -0.009)
        elif focus_role in {"OBJECT", "SUBJECT"}:
            scale = max(scale, 1.070)
            dy = min(dy, -0.010)
        elif focus_role == "PRIMARY":
            scale = max(scale, 1.080)
            dy = min(dy, -0.011)
        elif focus_role == "STATE":
            scale = max(scale, 1.095)
            dy = min(dy, -0.013)
        elif focus_role == "RESULT":
            scale = max(scale, 1.105)
            dy = min(dy, -0.014)

        strength = 0.78 + energy * 0.22
        # Relationship motion may point across the whole canvas. Keep the semantic
        # direction, but cap one-shot displacement so sparse scenes cannot create a
        # collision just because subject/object authored positions are far apart.
        dx = max(-0.10, min(0.10, dx * strength))
        dy = max(-0.10, min(0.10, dy * strength))
        scale = 1.0 + (scale - 1.0) * strength
        cohort_gain = max(0.0, min(1.0, cohort_gain))
        dx *= cohort_gain
        dy *= cohort_gain
        scale = 1.0 + (scale - 1.0) * cohort_gain
        return MotionProgram(
            name=f"{pattern.value.lower()}_{program.name}",
            settle_progress=settle,
            keyframes=(
                MotionKeyframe(
                    0.0,
                    first.dx,
                    first.dy,
                    first.scale,
                    first.easing,
                ),
                MotionKeyframe(
                    accent_progress,
                    dx,
                    dy,
                    scale,
                    "ease_out_cubic",
                ),
                MotionKeyframe(
                    settle,
                    0.0,
                    0.0,
                    1.0,
                    "ease_out_cubic",
                ),
                MotionKeyframe(1.0, 0.0, 0.0, 1.0, "smoothstep"),
            ),
        )

    @staticmethod
    def _apply_density_budget(
        program: MotionProgram,
        *,
        count: int,
        primary: bool,
        focus_role: str = "SUPPORT",
        geometry_locked: bool = False,
    ) -> MotionProgram:
        """Bound global motion as scene density grows while preserving final geometry."""
        if geometry_locked:
            return program
        role = str(focus_role or "SUPPORT").upper()
        if count <= 3:
            density = 1.0
            max_offset = 0.12 if primary else 0.075
            scale_factor = 1.0
            max_scale = 1.11 if role == "RESULT" else (1.095 if primary else 1.055)
        elif count <= 6:
            density = 0.78
            max_offset = 0.085 if primary else 0.055
            scale_factor = 0.82
            max_scale = 1.09 if role == "RESULT" else (1.08 if primary else 1.05)
        elif count <= 10:
            density = 0.60
            max_offset = 0.060 if primary else 0.040
            scale_factor = 0.65
            max_scale = 1.07 if role == "RESULT" else (1.06 if primary else 1.045)
        else:
            density = 0.48
            max_offset = 0.045 if primary else 0.030
            scale_factor = 0.52
            max_scale = 1.05 if role == "RESULT" else (1.045 if primary else 1.035)

        frames: list[MotionKeyframe] = []
        for frame in program.keyframes:
            dx = max(-max_offset, min(max_offset, frame.dx * density))
            dy = max(-max_offset, min(max_offset, frame.dy * density))
            scale = 1.0 + (frame.scale - 1.0) * scale_factor
            # Avoid dramatic zooms on dense scenes; Composition owns final size.
            scale = max(0.92 if primary else 0.95, min(max_scale, scale))
            if abs(frame.progress - program.settle_progress) <= 1e-9 or frame.progress >= 1.0 - 1e-9:
                dx, dy, scale = 0.0, 0.0, 1.0
            frames.append(MotionKeyframe(frame.progress, dx, dy, scale, frame.easing))
        return MotionProgram(
            name=f"density_safe_{program.name}" if count > 3 else program.name,
            keyframes=tuple(frames),
            settle_progress=program.settle_progress,
        )

    @staticmethod
    def _is_family_secondary(asset: VisualAsset | None) -> bool:
        return bool(
            asset is not None
            and asset.parent_asset_id
            and asset.render_as_family_canvas
        )

    @staticmethod
    def _primary_item(
        beat: StoryBeat | None,
        items: list[LayoutItem],
        *,
        preferred_asset_id: str | None = None,
    ) -> LayoutItem:
        if preferred_asset_id:
            preferred = next((item for item in items if item.asset_id == preferred_asset_id), None)
            if preferred is not None:
                return preferred
        primary_id = beat.primary_asset_ids[0] if beat is not None and beat.primary_asset_ids else None
        return next((item for item in items if item.asset_id == primary_id), items[0])

    @staticmethod
    def _target_item(
        beat: StoryBeat,
        items: list[LayoutItem],
        primary_item: LayoutItem,
        *,
        preferred_asset_id: str | None = None,
    ) -> LayoutItem | None:
        if preferred_asset_id:
            preferred = next((item for item in items if item.asset_id == preferred_asset_id), None)
            if preferred is not None and preferred.asset_id != primary_item.asset_id:
                return preferred
        support_ids = set(beat.support_asset_ids)
        support = next(
            (item for item in items if item.asset_id in support_ids and item.asset_id != primary_item.asset_id),
            None,
        )
        if support is not None:
            return support
        return next((item for item in items if item.asset_id != primary_item.asset_id), None)

    @staticmethod
    def _interaction_vector(
        *,
        item: LayoutItem,
        primary_item: LayoutItem,
        target_item: LayoutItem | None,
    ) -> tuple[float, float]:
        if target_item is None:
            return (0.0, 0.0)
        if item.asset_id == primary_item.asset_id:
            return (target_item.x - item.x, target_item.y - item.y)
        return (primary_item.x - item.x, primary_item.y - item.y)
