from __future__ import annotations

from app.choreography import ChoreographyPattern, ChoreographyPlan, HookKind
from app.models import AssetActivation, CompositionBeat, LayoutItem, MotionCue, StoryBeat, VisualAsset
from app.motion.compiler import MotionCompiler
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

            for index, slot in enumerate(ordered_slots):
                item = slot.item
                asset = by_asset.get(item.asset_id)
                family_secondary = self._is_family_secondary(asset)
                interaction_vector = self._interaction_vector(
                    item=item,
                    primary_item=primary_item,
                    target_item=target_item,
                )
                participant_role = (
                    directive.participant_role(item.asset_id).value
                    if directive is not None
                    else "SUPPORT"
                )
                activation = activation_by_asset.get(item.asset_id)
                (
                    momentary_focus,
                    focus_role,
                    focus_source,
                    focus_strength,
                    semantic_role,
                ) = self._semantic_focus_profile(
                    beat=beat,
                    activation=activation,
                    participant_role=participant_role,
                    static_primary=(item is primary_item),
                )
                continuity_source = previous_items.get(item.asset_id)
                # Continuity is allowed only for the exact same visual asset. A semantic
                # handoff between unrelated illustrations must not start the new artwork
                # from the previous artwork's screen position; that was the source of
                # large cross-screen sweeps on dense/new Final Packages.
                if family_secondary:
                    program = self.primitives.build_family_secondary()
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
                state_target = bool(
                    directive is not None
                    and any(
                        row.asset_id == item.asset_id and row.meaningful
                        for row in directive.state_transitions
                    )
                )
                if not family_secondary:
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
                            "semantic_role": semantic_role,
                            "visual_focus": (
                                str(activation.visual_focus).upper()
                                if activation is not None and activation.visual_focus
                                else None
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
                            }
                            if directive is not None
                            else None
                        ),
                    )
                )
            previous_layout = layout
        return cues

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

        if visual_focus == "CONTEXT":
            return False, "CONTEXT", "authored_context", 0.0, semantic_role

        if visual_focus == "RESULT":
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

        # Explicit result semantics are the strongest payoff. This never fabricates
        # RESULT: it only reacts to Choreography/Final Package evidence already present.
        if focus_role == "RESULT":
            scale = max(scale, 1.105)
            dy = min(dy, -0.014)

        strength = 0.78 + energy * 0.22
        # Relationship motion may point across the whole canvas. Keep the semantic
        # direction, but cap one-shot displacement so sparse scenes cannot create a
        # collision just because subject/object authored positions are far apart.
        dx = max(-0.06, min(0.06, dx * strength))
        dy = max(-0.06, min(0.06, dy * strength))
        scale = 1.0 + (scale - 1.0) * strength
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
