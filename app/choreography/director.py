from __future__ import annotations

from collections import defaultdict

from app.models import PackageModel, StoryBeat, VisualAsset

from .actions import ActionDecision, SemanticActionResolver
from .binding import AssetBinding, SemanticAssetBinder
from .continuity import ContinuityResolver
from .models import (
    ChoreographyDirective,
    ChoreographyPlan,
    ChoreographySequence,
    HookKind,
    HookMechanism,
    SequencePhase,
)
from .sequence import SequenceGrouper


class ChoreographyDirector:
    """Direct story beats as continuous visual sequences.

    Choreography owns narrative continuity, semantic focus, interaction intent and
    viewer-retention cadence. It explicitly does *not* own layout coordinates or render
    implementation. Composition remains the authority for resting positions; Motion
    compiles these directives into trajectories.
    """

    REHOOK_MIN_SECONDS = 5.5
    REHOOK_TARGET_SECONDS = 8.0
    REHOOK_MAX_SECONDS = 10.5

    def __init__(self) -> None:
        self.grouper = SequenceGrouper()
        self.actions = SemanticActionResolver()
        self.binding = SemanticAssetBinder()
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

        decisions: dict[str, ActionDecision] = {
            beat.id: self.actions.resolve(scene_by_id.get(beat.scene_id), beat)
            for beat in beats
        }
        bindings: dict[str, AssetBinding] = {
            beat.id: self.binding.bind(
                scene=scene_by_id.get(beat.scene_id),
                assets=assets_by_scene.get(beat.scene_id, []),
                action=decisions[beat.id].action,
            )
            for beat in beats
        }

        groups = self.grouper.group(beats)
        sequence_hooks = self._schedule_hooks(groups, decisions)

        sequences: list[ChoreographySequence] = []
        directives: list[ChoreographyDirective] = []
        previous_focus: str | None = None

        for sequence_index, group in enumerate(groups, start=1):
            sequence_id = f"sequence-{sequence_index:03d}"
            hook, mechanism = sequence_hooks.get(sequence_id, (HookKind.NONE, HookMechanism.NONE))
            start = self._audio_start(group[0])
            end = self._audio_end(group[-1])
            peak = max(decisions[beat.id].tension for beat in group)
            sequences.append(ChoreographySequence(
                id=sequence_id,
                beat_ids=tuple(beat.id for beat in group),
                start=start,
                end=end,
                hook=hook,
                hook_mechanism=mechanism,
                tension_peak=peak,
            ))

            for index, beat in enumerate(group):
                decision = decisions[beat.id]
                binding = bindings[beat.id]
                phase = self._phase(index, len(group), decision.action)
                beat_hook = self._beat_hook(hook, index, len(group), decision.action)
                beat_mechanism = mechanism if beat_hook != HookKind.NONE else HookMechanism.NONE

                phase_boost = 0.08 if phase == SequencePhase.CONSEQUENCE else 0.0
                hook_boost = 0.18 if beat_hook != HookKind.NONE else 0.0
                energy = min(1.0, decision.energy + phase_boost + hook_boost)

                current_asset_ids = set(beat.primary_asset_ids + beat.support_asset_ids)
                # Asset binding may select a cutout that Story classified as support.
                # The cutout still belongs to this scene/layout; only its choreography
                # role changes.
                focus = binding.focus_asset_id
                if focus is None or focus not in current_asset_ids:
                    focus = beat.primary_asset_ids[0] if beat.primary_asset_ids else None
                interaction = binding.interaction_asset_id
                if interaction not in current_asset_ids:
                    interaction = None
                continuity = self.continuity.decide_focus(previous_focus, focus, current_asset_ids)

                directives.append(ChoreographyDirective(
                    beat_id=beat.id,
                    sequence_id=sequence_id,
                    phase=phase,
                    action=decision.action,
                    hook=beat_hook,
                    hook_mechanism=beat_mechanism,
                    energy=energy,
                    tension=decision.tension,
                    primary_asset_id=focus,
                    interaction_asset_id=interaction,
                    actor_asset_ids=binding.actor_asset_ids,
                    support_asset_ids=tuple(
                        asset_id
                        for asset_id in beat.primary_asset_ids + beat.support_asset_ids
                        if asset_id != focus
                    ),
                    semantic_labels=decision.labels,
                    relationship=decision.relationship,
                    continuity_from=continuity.from_asset_id,
                    continuity_mode=continuity.mode,
                    pacing_bias=decision.pacing_bias,
                ))
                if focus:
                    previous_focus = focus

        plan = ChoreographyPlan(sequences=tuple(sequences), directives=tuple(directives))
        plan.validate(beat.id for beat in beats)
        return plan

    def _schedule_hooks(
        self,
        groups: list[list[StoryBeat]],
        decisions: dict[str, ActionDecision],
    ) -> dict[str, tuple[HookKind, HookMechanism]]:
        output: dict[str, tuple[HookKind, HookMechanism]] = {}
        if not groups:
            return output

        first_mechanism = self._mechanism_for_group(groups[0], decisions, opening=True)
        output["sequence-001"] = (HookKind.OPEN, first_mechanism)
        last_hook_time = self._audio_start(groups[0][0])
        previous_mechanism = first_mechanism

        for index, group in enumerate(groups[1:], start=2):
            sequence_id = f"sequence-{index:03d}"
            start = self._audio_start(group[0])
            elapsed = start - last_hook_time
            peak = max(decisions[beat.id].tension for beat in group)
            strong_change = any(
                decisions[beat.id].action
                in {"REJECT", "BLOCK", "LOOP", "COMPARE", "PROTECT", "RESOLVE", "TRAVEL"}
                for beat in group
            )
            due = elapsed >= self.REHOOK_TARGET_SECONDS
            opportunity = elapsed >= self.REHOOK_MIN_SECONDS and (peak >= 0.66 or strong_change)
            forced = elapsed >= self.REHOOK_MAX_SECONDS
            if opportunity or due or forced:
                mechanism = self._mechanism_for_group(group, decisions, opening=False)
                mechanism = self._avoid_repeat(mechanism, previous_mechanism, group, decisions)
                output[sequence_id] = (HookKind.REHOOK, mechanism)
                last_hook_time = start
                previous_mechanism = mechanism

        final_id = f"sequence-{len(groups):03d}"
        final_group = groups[-1]
        has_resolution = any(
            decisions[beat.id].action in {"RESOLVE", "PROTECT", "REJECT", "BLOCK"}
            for beat in final_group
        )
        if has_resolution and len(groups) > 1:
            output[final_id] = (HookKind.PAYOFF, HookMechanism.PAYOFF)
        return output

    @staticmethod
    def _mechanism_for_group(
        group: list[StoryBeat],
        decisions: dict[str, ActionDecision],
        *,
        opening: bool,
    ) -> HookMechanism:
        actions = {decisions[beat.id].action for beat in group}
        peak = max(decisions[beat.id].tension for beat in group)

        if opening:
            if actions & {"REJECT", "BLOCK"} or peak >= 0.86:
                return HookMechanism.CONTRADICTION
            return HookMechanism.CURIOSITY
        if actions & {"REJECT", "BLOCK"}:
            return HookMechanism.REVERSAL
        if "LOOP" in actions:
            return HookMechanism.ESCALATION
        if "COMPARE" in actions:
            return HookMechanism.CONTRAST
        if "RESOLVE" in actions:
            return HookMechanism.PAYOFF
        if actions & {"TRAVEL", "SCAN", "PROTECT"}:
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
    def _phase(index: int, count: int, action: str) -> SequencePhase:
        if count <= 1:
            return SequencePhase.CONSEQUENCE
        if index == 0:
            return SequencePhase.SETUP
        if index == count - 1:
            if action in {"REJECT", "BLOCK", "RESOLVE", "PROTECT", "LOCK"}:
                return SequencePhase.CONSEQUENCE
            return SequencePhase.HANDOFF
        return SequencePhase.ACTION

    @staticmethod
    def _beat_hook(
        sequence_hook: HookKind,
        index: int,
        count: int,
        action: str,
    ) -> HookKind:
        if sequence_hook == HookKind.NONE:
            return HookKind.NONE
        if sequence_hook == HookKind.OPEN:
            return HookKind.OPEN if index < min(2, count) else HookKind.NONE
        if sequence_hook == HookKind.REHOOK:
            return HookKind.REHOOK if index == 0 or action in {"REJECT", "BLOCK", "LOOP"} else HookKind.NONE
        if sequence_hook == HookKind.PAYOFF:
            return HookKind.PAYOFF if index >= max(0, count - 2) else HookKind.NONE
        return HookKind.NONE

    @staticmethod
    def _audio_start(beat: StoryBeat) -> float:
        return beat.audio_start if beat.audio_start is not None else beat.start

    @staticmethod
    def _audio_end(beat: StoryBeat) -> float:
        return beat.audio_end if beat.audio_end is not None else beat.end
