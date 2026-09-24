from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Iterable


class SequencePhase(StrEnum):
    SETUP = "SETUP"
    ACTION = "ACTION"
    CONSEQUENCE = "CONSEQUENCE"
    HANDOFF = "HANDOFF"


class HookKind(StrEnum):
    NONE = "NONE"
    OPEN = "OPEN"
    REHOOK = "REHOOK"
    PAYOFF = "PAYOFF"


class HookMechanism(StrEnum):
    """Story-retention mechanism, independent of any specific topic or scene id."""

    NONE = "NONE"
    CURIOSITY = "CURIOSITY"
    CONTRADICTION = "CONTRADICTION"
    ESCALATION = "ESCALATION"
    REVERSAL = "REVERSAL"
    CONTRAST = "CONTRAST"
    PAYOFF = "PAYOFF"


class ContinuityMode(StrEnum):
    NONE = "NONE"
    SAME_ASSET = "SAME_ASSET"
    SEMANTIC_HANDOFF = "SEMANTIC_HANDOFF"


class ParticipantRole(StrEnum):
    SUBJECT = "SUBJECT"
    OBJECT = "OBJECT"
    RESULT = "RESULT"
    ACTOR = "ACTOR"
    SUPPORT = "SUPPORT"


class EventFlowStage(StrEnum):
    """Reference-style semantic phases inside one Final Package event."""

    ESTABLISH = "ESTABLISH"
    ADD = "ADD"
    INTERACT = "INTERACT"
    REACT = "REACT"
    PAYOFF = "PAYOFF"
    RELEASE = "RELEASE"


class VisualGrammarStage(StrEnum):
    ENTER = "ENTER"
    READ = "READ"
    ADD = "ADD"
    RELATE = "RELATE"
    RESULT = "RESULT"
    RELEASE = "RELEASE"


class ChoreographyPattern(StrEnum):
    """Generic reference-style visual construction patterns.

    Patterns describe how meaning is progressively staged. They are not animation
    presets and never own final geometry or speech timing.
    """

    STANDARD = "STANDARD"
    PROGRESSIVE_BUILD = "PROGRESSIVE_BUILD"
    FOCUS_TRANSFER = "FOCUS_TRANSFER"
    STATE_TRANSFORM = "STATE_TRANSFORM"
    CAUSE_EFFECT_CHAIN = "CAUSE_EFFECT_CHAIN"


@dataclass(frozen=True, slots=True)
class AssetRequirement:
    semantic_unit_id: str
    participant_role: ParticipantRole
    reason: str
    required_for_action: str
    satisfied: bool
    bound_asset_id: str | None = None
    confidence: float = 1.0


@dataclass(frozen=True, slots=True)
class VisualStateTransition:
    asset_id: str
    from_state: str
    to_state: str
    reason: str
    semantic_unit_id: str | None = None
    confidence: float = 1.0
    meaningful: bool = True
    authority: str = "INFERRED"


@dataclass(frozen=True, slots=True)
class InteractionIntent:
    semantic_action: str
    relationship: str | None
    subject_asset_id: str | None
    object_asset_id: str | None
    result_asset_id: str | None = None
    subject_unit_id: str | None = None
    object_unit_id: str | None = None
    result_unit_id: str | None = None
    authority: str = "CHOREOGRAPHY_ACTION"
    confidence: float = 0.0
    executable: bool = False
    requires_state_change: bool = False
    evidence: tuple[str, ...] = ()

    @property
    def participant_asset_ids(self) -> tuple[str, ...]:
        rows = (
            self.subject_asset_id,
            self.object_asset_id,
            self.result_asset_id,
        )
        return tuple(dict.fromkeys(value for value in rows if value))


@dataclass(frozen=True, slots=True)
class EventFlowStep:
    """One explicit semantic beat inside a Final Package event visual sentence.

    Choreography owns WHO participates and WHAT semantic phase occurs. Motion still owns
    trajectories, amplitudes and final rendering. Context assets intentionally never
    become step focus unless the Final Package authored them in another semantic role.
    """

    stage: EventFlowStage
    focus_asset_id: str | None = None
    participant_asset_ids: tuple[str, ...] = ()
    source_asset_id: str | None = None
    target_asset_id: str | None = None
    result_asset_id: str | None = None
    relationship: str | None = None
    semantic_action: str | None = None
    authority: str = "FINAL_PACKAGE_SEMANTIC_EVENT"


@dataclass(frozen=True, slots=True)
class SemanticEventFlow:
    """One Final Package semantic event compiled into a visual mini-story contract."""

    event_id: str
    order: int | None = None
    dependency_ids: tuple[str, ...] = ()
    leader_asset_ids: tuple[str, ...] = ()
    participant_asset_ids: tuple[str, ...] = ()
    context_asset_ids: tuple[str, ...] = ()
    result_asset_ids: tuple[str, ...] = ()
    text_anchor_asset_ids: tuple[str, ...] = ()
    interactions: tuple[InteractionIntent, ...] = ()
    stages: tuple[EventFlowStage, ...] = ()
    steps: tuple[EventFlowStep, ...] = ()
    handoff_to_event_id: str | None = None
    handoff_to_asset_id: str | None = None
    confidence: float = 0.0
    authority: str = "FINAL_PACKAGE_SEMANTIC_EVENT"
    evidence: tuple[str, ...] = ()

    @property
    def asset_ids(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys((
            *self.leader_asset_ids,
            *self.participant_asset_ids,
            *self.context_asset_ids,
            *self.result_asset_ids,
            *self.text_anchor_asset_ids,
        )))

    @property
    def primary_leader_asset_id(self) -> str | None:
        return self.leader_asset_ids[0] if self.leader_asset_ids else None

    @property
    def focus_path_asset_ids(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(
            step.focus_asset_id for step in self.steps if step.focus_asset_id
        ))


@dataclass(frozen=True, slots=True)
class ChoreographyDirective:
    beat_id: str
    sequence_id: str
    phase: SequencePhase
    action: str
    pattern: ChoreographyPattern = ChoreographyPattern.STANDARD
    hook: HookKind = HookKind.NONE
    hook_mechanism: HookMechanism = HookMechanism.NONE
    energy: float = 0.5
    tension: float = 0.0
    primary_asset_id: str | None = None
    interaction_asset_id: str | None = None
    actor_asset_ids: tuple[str, ...] = ()
    support_asset_ids: tuple[str, ...] = ()
    semantic_labels: tuple[str, ...] = ()
    semantic_unit_ids: tuple[str, ...] = ()
    relationship: str | None = None
    interaction: InteractionIntent | None = None
    interactions: tuple[InteractionIntent, ...] = ()
    state_transitions: tuple[VisualStateTransition, ...] = ()
    continuity_from: str | None = None
    continuity_mode: ContinuityMode = ContinuityMode.NONE
    pacing_bias: float = 1.0
    package_evidence: tuple[str, ...] = ()
    grammar_stages: tuple[VisualGrammarStage, ...] = ()
    asset_requirements: tuple[AssetRequirement, ...] = ()
    event_flows: tuple[SemanticEventFlow, ...] = ()

    def participant_role(self, asset_id: str) -> ParticipantRole:
        # A declared human actor keeps ACTOR semantics even when an explicit relationship
        # names it as subject/object. This lets Motion express guide/reaction behavior
        # instead of treating a person like a generic moving object.
        if asset_id in self.actor_asset_ids:
            return ParticipantRole.ACTOR
        rows = self.interactions or ((self.interaction,) if self.interaction is not None else ())
        for interaction in rows:
            if asset_id == interaction.result_asset_id:
                return ParticipantRole.RESULT
        for interaction in rows:
            if asset_id == interaction.subject_asset_id:
                return ParticipantRole.SUBJECT
            if asset_id == interaction.object_asset_id:
                return ParticipantRole.OBJECT
        return ParticipantRole.SUPPORT

    @property
    def has_meaningful_state_change(self) -> bool:
        return any(row.meaningful and row.from_state != row.to_state for row in self.state_transitions)

    @property
    def event_focus_path_asset_ids(self) -> tuple[str, ...]:
        """Ordered authored focus handoff path across all semantic events in this beat."""
        return tuple(dict.fromkeys(
            asset_id
            for flow in self.event_flows
            for asset_id in flow.focus_path_asset_ids
        ))


@dataclass(frozen=True, slots=True)
class ChoreographySequence:
    id: str
    beat_ids: tuple[str, ...]
    start: float
    end: float
    hook: HookKind = HookKind.NONE
    hook_mechanism: HookMechanism = HookMechanism.NONE
    tension_peak: float = 0.0
    interaction_count: int = 0
    meaningful_state_change_count: int = 0
    grammar_stages: tuple[VisualGrammarStage, ...] = ()


@dataclass(frozen=True, slots=True)
class ChoreographyPlan:
    sequences: tuple[ChoreographySequence, ...] = ()
    directives: tuple[ChoreographyDirective, ...] = ()
    _by_beat: dict[str, ChoreographyDirective] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_by_beat", {row.beat_id: row for row in self.directives})

    def for_beat(self, beat_id: str) -> ChoreographyDirective | None:
        return self._by_beat.get(beat_id)

    def hook_beats(self) -> tuple[str, ...]:
        return tuple(row.beat_id for row in self.directives if row.hook != HookKind.NONE)

    def validate(self, beat_ids: Iterable[str]) -> None:
        expected = tuple(beat_ids)
        actual = tuple(row.beat_id for row in self.directives)
        if actual != expected:
            raise ValueError("choreography directives must preserve story beat order exactly")
        if self.directives and self.directives[0].hook != HookKind.OPEN:
            raise ValueError("choreography must open with an explicit hook")
        for directive in self.directives:
            event_ids = [flow.event_id for flow in directive.event_flows]
            if len(event_ids) != len(set(event_ids)):
                raise ValueError("choreography event flows must have unique event ids per beat")
            explicit_orders = [flow.order for flow in directive.event_flows if flow.order is not None]
            if explicit_orders != sorted(explicit_orders):
                raise ValueError("choreography event flows must preserve authored event order")
            order_by_id = {flow.event_id: flow.order for flow in directive.event_flows}
            flow_by_id = {flow.event_id: flow for flow in directive.event_flows}
            for flow in directive.event_flows:
                if flow.stages and flow.stages[-1] != EventFlowStage.RELEASE:
                    raise ValueError("semantic event flow must release after its final phase")
                if flow.steps and flow.steps[-1].stage != EventFlowStage.RELEASE:
                    raise ValueError("semantic event flow steps must end in RELEASE")
                if flow.result_asset_ids and EventFlowStage.PAYOFF not in flow.stages:
                    raise ValueError("semantic event result must compile a payoff phase")
                if flow.result_asset_ids and not any(
                    step.stage == EventFlowStage.PAYOFF for step in flow.steps
                ):
                    raise ValueError("semantic event result must own an explicit payoff step")
                if flow.handoff_to_event_id is not None:
                    target_flow = flow_by_id.get(flow.handoff_to_event_id)
                    if target_flow is None:
                        raise ValueError("semantic event handoff must target an event in the beat")
                    if (
                        flow.order is not None
                        and target_flow.order is not None
                        and target_flow.order <= flow.order
                    ):
                        raise ValueError("semantic event handoff must move forward")
                    if (
                        flow.handoff_to_asset_id is not None
                        and flow.handoff_to_asset_id not in target_flow.asset_ids
                    ):
                        raise ValueError("semantic event handoff asset must belong to target event")
                for dependency in flow.dependency_ids:
                    dependency_order = order_by_id.get(dependency)
                    if (
                        dependency_order is not None
                        and flow.order is not None
                        and dependency_order >= flow.order
                    ):
                        raise ValueError("semantic event dependency must precede dependent event")

        for sequence in self.sequences:
            if not sequence.beat_ids:
                raise ValueError("choreography sequence cannot be empty")
            if sequence.hook == HookKind.NONE and sequence.hook_mechanism != HookMechanism.NONE:
                raise ValueError("non-hook sequence cannot own a hook mechanism")
