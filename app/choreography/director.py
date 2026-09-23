from __future__ import annotations

from collections import defaultdict

from app.models import PackageModel, StoryBeat, VisualAsset

from .actions import ActionDecision, SemanticActionResolver
from .binding import AssetBinding, SemanticAssetBinder
from .continuity import ContinuityResolver
from .grammar import ReferenceGrammarPlanner
from .interactions import InteractionCompiler
from .models import (
    ChoreographyDirective,
    ChoreographyPlan,
    ChoreographySequence,
    ChoreographyPattern,
    HookKind,
    HookMechanism,
    InteractionIntent,
    SequencePhase,
    VisualStateTransition,
)
from .requirements import AssetRequirementCompiler
from .sequence import SequenceGrouper
from .state import VisualStateCompiler


class ChoreographyDirector:
    """Direct Story beats as continuous, stateful visual sequences.

    Story owns meaning. Choreography owns what happens visually: interactions, state
    changes, focus continuity, and retention beats. Composition remains the sole layout
    authority and Motion remains the sole trajectory authority.
    """

    REHOOK_MIN_SECONDS = 5.5
    REHOOK_TARGET_SECONDS = 8.0
    REHOOK_MAX_SECONDS = 10.5

    def __init__(self) -> None:
        self.grouper = SequenceGrouper()
        self.actions = SemanticActionResolver()
        self.binding = SemanticAssetBinder()
        self.interactions = InteractionCompiler()
        self.states = VisualStateCompiler()
        self.grammar = ReferenceGrammarPlanner()
        self.requirements = AssetRequirementCompiler()
        self.continuity = ContinuityResolver()

    def plan(
        self,
        package: PackageModel,
        beats: list[StoryBeat],
        assets: list[VisualAsset],
    ) -> ChoreographyPlan:
        if not beats:
            return ChoreographyPlan()

        scene_by_id = {scene.id: scene for scene in package.scenes}
        assets_by_scene: dict[str, list[VisualAsset]] = defaultdict(list)
        for asset in assets:
            assets_by_scene[asset.scene_id].append(asset)

        decisions: dict[str, ActionDecision] = {}
        bindings: dict[str, AssetBinding] = {}
        interaction_sets: dict[str, tuple[InteractionIntent, ...]] = {}
        primary_interactions: dict[str, InteractionIntent | None] = {}
        transitions: dict[str, tuple[VisualStateTransition, ...]] = {}
        requirements: dict[str, tuple] = {}

        for beat in beats:
            scene = scene_by_id.get(beat.scene_id)
            decision = self.actions.resolve(scene, beat)
            binding = self.binding.bind(
                scene=scene,
                assets=assets_by_scene.get(beat.scene_id, []),
                action=decision.action,
                beat=beat,
            )
            all_interactions = self.interactions.compile_all(beat, binding, decision)
            primary_interaction = self.interactions.primary(all_interactions, binding)
            state_changes = self.states.compile_all(
                beat,
                binding,
                decision.action,
                all_interactions,
            )
            asset_requirements = self.requirements.compile_all(
                beat, binding, all_interactions, decision.action
            )
            decisions[beat.id] = decision
            bindings[beat.id] = binding
            interaction_sets[beat.id] = all_interactions
            primary_interactions[beat.id] = primary_interaction
            transitions[beat.id] = state_changes
            requirements[beat.id] = asset_requirements

        groups = self.grouper.group(beats)
        sequence_hooks = self._schedule_hooks(
            groups, decisions, primary_interactions, transitions
        )

        sequences: list[ChoreographySequence] = []
        directives: list[ChoreographyDirective] = []
        previous_focus: str | None = None

        for sequence_index, group in enumerate(groups, start=1):
            sequence_id = f"sequence-{sequence_index:03d}"
            hook, mechanism = sequence_hooks.get(sequence_id, (HookKind.NONE, HookMechanism.NONE))
            start = self._audio_start(group[0])
            end = self._audio_end(group[-1])
            peak = max(decisions[beat.id].tension for beat in group)
            interaction_count = sum(
                1
                for beat in group
                for interaction in interaction_sets[beat.id]
                if interaction.executable
            )
            meaningful_change_count = sum(
                1
                for beat in group
                if any(row.meaningful for row in transitions[beat.id])
            )
            sequence_grammar = []

            for index, beat in enumerate(group):
                decision = decisions[beat.id]
                binding = bindings[beat.id]
                all_interactions = interaction_sets[beat.id]
                interaction_intent = primary_interactions[beat.id]
                state_changes = transitions[beat.id]
                phase = self._phase(index, len(group), decision.action, beat)
                grammar_stages = self.grammar.stages_for_beat(
                    beat=beat,
                    index=index,
                    count=len(group),
                    phase=phase,
                    interaction=interaction_intent,
                    transitions=state_changes,
                )
                sequence_grammar.extend(grammar_stages)
                beat_hook = self._beat_hook(
                    hook,
                    index,
                    len(group),
                    decision.action,
                    state_changes,
                )
                beat_mechanism = mechanism if beat_hook != HookKind.NONE else HookMechanism.NONE

                phase_boost = 0.08 if phase == SequencePhase.CONSEQUENCE else 0.0
                hook_boost = 0.18 if beat_hook != HookKind.NONE else 0.0
                energy = min(1.0, decision.energy + phase_boost + hook_boost)

                current_asset_ids = set(beat.primary_asset_ids + beat.support_asset_ids)
                has_authored_focus = any(
                    row.visual_focus
                    for row in beat.asset_activations
                )
                focus = (
                    binding.focus_asset_id
                    if has_authored_focus
                    else self.interactions.preferred_focus(interaction_intent, binding)
                )
                if focus is None or focus not in current_asset_ids:
                    focus = binding.focus_asset_id
                if focus is None or focus not in current_asset_ids:
                    focus = beat.primary_asset_ids[0] if beat.primary_asset_ids else None

                interaction_asset = binding.interaction_asset_id
                if interaction_intent is not None:
                    if focus == interaction_intent.subject_asset_id:
                        interaction_asset = interaction_intent.object_asset_id
                    elif focus == interaction_intent.object_asset_id:
                        interaction_asset = interaction_intent.subject_asset_id
                    else:
                        interaction_asset = (
                            interaction_intent.object_asset_id
                            or interaction_intent.subject_asset_id
                        )
                if interaction_asset not in current_asset_ids or interaction_asset == focus:
                    interaction_asset = None

                continuity = self.continuity.decide_focus(previous_focus, focus, current_asset_ids)
                pattern = self._pattern_for(
                    beat,
                    all_interactions,
                    state_changes,
                )
                context = beat.semantic_context
                semantic_unit_ids = tuple(
                    entity.unit_id for entity in (context.entities if context else [])
                )
                package_evidence = tuple(context.evidence if context else [])

                directives.append(ChoreographyDirective(
                    beat_id=beat.id,
                    sequence_id=sequence_id,
                    phase=phase,
                    action=decision.action,
                    pattern=pattern,
                    hook=beat_hook,
                    hook_mechanism=beat_mechanism,
                    energy=energy,
                    tension=max(decision.tension, context.tension if context else 0.0),
                    primary_asset_id=focus,
                    interaction_asset_id=interaction_asset,
                    actor_asset_ids=binding.actor_asset_ids,
                    support_asset_ids=tuple(
                        asset_id
                        for asset_id in beat.primary_asset_ids + beat.support_asset_ids
                        if asset_id != focus
                    ),
                    semantic_labels=decision.labels,
                    semantic_unit_ids=semantic_unit_ids,
                    relationship=(
                        interaction_intent.relationship
                        if interaction_intent is not None
                        else decision.relationship
                    ),
                    interaction=interaction_intent,
                    interactions=all_interactions,
                    state_transitions=state_changes,
                    continuity_from=continuity.from_asset_id,
                    continuity_mode=continuity.mode,
                    pacing_bias=decision.pacing_bias,
                    package_evidence=package_evidence,
                    grammar_stages=grammar_stages,
                    asset_requirements=requirements[beat.id],
                ))
                if focus:
                    previous_focus = focus

            sequences.append(ChoreographySequence(
                id=sequence_id,
                beat_ids=tuple(beat.id for beat in group),
                start=start,
                end=end,
                hook=hook,
                hook_mechanism=mechanism,
                tension_peak=peak,
                interaction_count=interaction_count,
                meaningful_state_change_count=meaningful_change_count,
                grammar_stages=tuple(dict.fromkeys(sequence_grammar)),
            ))

        plan = ChoreographyPlan(sequences=tuple(sequences), directives=tuple(directives))
        plan.validate(beat.id for beat in beats)
        return plan

    def _schedule_hooks(
        self,
        groups: list[list[StoryBeat]],
        decisions: dict[str, ActionDecision],
        interactions: dict[str, InteractionIntent | None],
        transitions: dict[str, tuple[VisualStateTransition, ...]],
    ) -> dict[str, tuple[HookKind, HookMechanism]]:
        output: dict[str, tuple[HookKind, HookMechanism]] = {}
        if not groups:
            return output

        first_mechanism = self._mechanism_for_group(
            groups[0], decisions, interactions, transitions, opening=True,
        )
        output["sequence-001"] = (HookKind.OPEN, first_mechanism)
        last_hook_time = self._audio_start(groups[0][0])
        previous_mechanism = first_mechanism

        for index, group in enumerate(groups[1:], start=2):
            sequence_id = f"sequence-{index:03d}"
            start = self._audio_start(group[0])
            elapsed = start - last_hook_time
            peak = max(decisions[beat.id].tension for beat in group)
            semantic_change = any(
                any(row.meaningful for row in transitions[beat.id])
                or (
                    interactions[beat.id] is not None
                    and interactions[beat.id].requires_state_change
                )
                or decisions[beat.id].action
                in {"REJECT", "BLOCK", "LOCK", "LOOP", "TRAVEL", "COMPARE", "PROTECT", "RESOLVE", "REACT", "CONNECT"}
                or self._story_role(beat) in {"COMPLICATION", "CONSEQUENCE", "RESOLUTION", "COMPARISON"}
                for beat in group
            )
            opportunity = elapsed >= self.REHOOK_MIN_SECONDS and semantic_change and peak >= 0.66
            due = elapsed >= self.REHOOK_TARGET_SECONDS and semantic_change
            sparse_legacy = all(beat.semantic_context is None for beat in group)
            forced = elapsed >= self.REHOOK_MAX_SECONDS and (semantic_change or sparse_legacy)
            if opportunity or due or forced:
                mechanism = self._mechanism_for_group(
                    group, decisions, interactions, transitions, opening=False,
                )
                mechanism = self._avoid_repeat(mechanism, previous_mechanism, group, decisions)
                output[sequence_id] = (HookKind.REHOOK, mechanism)
                last_hook_time = start
                previous_mechanism = mechanism

        final_id = f"sequence-{len(groups):03d}"
        final_group = groups[-1]
        has_resolution = any(
            self._story_role(beat) == "RESOLUTION"
            or decisions[beat.id].action in {"RESOLVE", "PROTECT"}
            for beat in final_group
        )
        if has_resolution and len(groups) > 1:
            output[final_id] = (HookKind.PAYOFF, HookMechanism.PAYOFF)
        return output

    def _mechanism_for_group(
        self,
        group: list[StoryBeat],
        decisions: dict[str, ActionDecision],
        interactions: dict[str, InteractionIntent | None],
        transitions: dict[str, tuple[VisualStateTransition, ...]],
        *,
        opening: bool,
    ) -> HookMechanism:
        actions = {decisions[beat.id].action for beat in group}
        roles = {self._story_role(beat) for beat in group}
        has_change = any(any(row.meaningful for row in transitions[beat.id]) for beat in group)
        has_interaction = any(interactions[beat.id] is not None for beat in group)

        if opening:
            if actions & {"REJECT", "BLOCK"} or "COMPLICATION" in roles:
                return HookMechanism.CONTRADICTION
            return HookMechanism.CURIOSITY
        if actions & {"REJECT", "BLOCK"} or "CONSEQUENCE" in roles:
            return HookMechanism.REVERSAL
        if "COMPARE" in actions or "COMPARISON" in roles:
            return HookMechanism.CONTRAST
        if "RESOLVE" in actions or "RESOLUTION" in roles:
            return HookMechanism.PAYOFF
        if "LOOP" in actions:
            return HookMechanism.ESCALATION
        if has_change or has_interaction:
            return HookMechanism.CURIOSITY
        return HookMechanism.ESCALATION

    @staticmethod
    def _avoid_repeat(
        mechanism: HookMechanism,
        previous: HookMechanism,
        group: list[StoryBeat],
        decisions: dict[str, ActionDecision],
    ) -> HookMechanism:
        if mechanism != previous:
            return mechanism
        actions = {decisions[beat.id].action for beat in group}
        if "COMPARE" in actions:
            return HookMechanism.CONTRAST
        if actions & {"REJECT", "BLOCK"}:
            return HookMechanism.REVERSAL
        if "LOOP" in actions:
            return HookMechanism.ESCALATION
        return HookMechanism.CURIOSITY if previous != HookMechanism.CURIOSITY else HookMechanism.ESCALATION

    @staticmethod
    def _phase(index: int, count: int, action: str, beat: StoryBeat) -> SequencePhase:
        role = ChoreographyDirector._story_role(beat)
        if role in {"CONSEQUENCE", "RESOLUTION"}:
            return SequencePhase.CONSEQUENCE
        if role == "ACTION":
            return SequencePhase.ACTION
        if count <= 1:
            return SequencePhase.CONSEQUENCE if action in {"REJECT", "BLOCK", "RESOLVE", "REACT"} else SequencePhase.SETUP
        if index == 0:
            return SequencePhase.SETUP
        if index == count - 1:
            if action in {"REJECT", "BLOCK", "RESOLVE", "PROTECT", "LOCK", "REACT"}:
                return SequencePhase.CONSEQUENCE
            return SequencePhase.HANDOFF
        return SequencePhase.ACTION

    @staticmethod
    def _beat_hook(
        sequence_hook: HookKind,
        index: int,
        count: int,
        action: str,
        transitions: tuple[VisualStateTransition, ...],
    ) -> HookKind:
        if sequence_hook == HookKind.NONE:
            return HookKind.NONE
        if sequence_hook == HookKind.OPEN:
            return HookKind.OPEN if index < min(2, count) else HookKind.NONE
        if sequence_hook == HookKind.REHOOK:
            # Re-hooks reset attention once at the sequence boundary. Meaning-bearing
            # actions later in the sequence keep their own choreography without being
            # mislabeled as additional hooks.
            return HookKind.REHOOK if index == 0 else HookKind.NONE
        if sequence_hook == HookKind.PAYOFF:
            return HookKind.PAYOFF if index >= max(0, count - 2) else HookKind.NONE
        return HookKind.NONE

    @staticmethod
    def _pattern_for(
        beat: StoryBeat,
        interactions: tuple[InteractionIntent, ...],
        transitions: tuple[VisualStateTransition, ...],
    ) -> ChoreographyPattern:
        # Explicit Final Package semantics outrank inferred choreography. The order here
        # intentionally mirrors the minimum-useful-metadata contract: state changes are
        # strongest, then executable relationships, then focus, then ordered build.
        if any(
            row.authority == "FINAL_PACKAGE_VISUAL_STATE" and row.meaningful
            for row in transitions
        ):
            return ChoreographyPattern.STATE_TRANSFORM

        authored_relations = [
            row
            for row in interactions
            if row.authority == "FINAL_PACKAGE_ASSET_RELATION" and row.executable
        ]
        if authored_relations:
            non_compare = [
                row
                for row in authored_relations
                if str(row.relationship or "").upper() not in {
                    "COMPARES_WITH",
                    "CONTRASTS_WITH",
                }
            ]
            if non_compare:
                return ChoreographyPattern.CAUSE_EFFECT_CHAIN

        if any(row.visual_focus for row in beat.asset_activations):
            return ChoreographyPattern.FOCUS_TRANSFER

        ordered = {
            row.sequence_order
            for row in beat.asset_activations
            if (
                row.source == "final_package_semantic_binding"
                and row.sequence_order is not None
            )
        }
        if len(ordered) >= 3:
            return ChoreographyPattern.PROGRESSIVE_BUILD

        return ChoreographyPattern.STANDARD

    @staticmethod
    def _story_role(beat: StoryBeat) -> str:
        return beat.semantic_context.story_role.upper() if beat.semantic_context else "CONTEXT"

    @staticmethod
    def _audio_start(beat: StoryBeat) -> float:
        return beat.audio_start if beat.audio_start is not None else beat.start

    @staticmethod
    def _audio_end(beat: StoryBeat) -> float:
        return beat.audio_end if beat.audio_end is not None else beat.end
