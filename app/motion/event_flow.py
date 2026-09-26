from __future__ import annotations

from dataclasses import dataclass

from app.choreography import ChoreographyDirective, EventFlowStage, EventFlowStep
from app.choreography.relation_contract import SEMANTIC_PROXY_AUTHORITIES


@dataclass(frozen=True, slots=True)
class MotionEventPhase:
    """One authored event-flow phase owned by a rendered visual."""

    event_id: str
    event_order: int | None
    stage: EventFlowStage
    step_index: int
    involvement: str
    focus_asset_id: str | None
    source_asset_id: str | None
    target_asset_id: str | None
    result_asset_id: str | None
    relationship: str | None
    semantic_action: str | None
    authority: str
    trigger_char_start: int | None = None
    trigger_char_end: int | None = None
    spoken_start: float | None = None
    spoken_end: float | None = None

    def to_payload(self) -> dict[str, object | None]:
        return {
            "event_id": self.event_id,
            "event_order": self.event_order,
            "stage": self.stage.value,
            "step_index": self.step_index,
            "involvement": self.involvement,
            "focus_asset_id": self.focus_asset_id,
            "source_asset_id": self.source_asset_id,
            "target_asset_id": self.target_asset_id,
            "result_asset_id": self.result_asset_id,
            "relationship": self.relationship,
            "semantic_action": self.semantic_action,
            "authority": self.authority,
            "trigger_char_start": self.trigger_char_start,
            "trigger_char_end": self.trigger_char_end,
            "spoken_start": self.spoken_start,
            "spoken_end": self.spoken_end,
        }


@dataclass(frozen=True, slots=True)
class MotionEventAssignment:
    """Motion-facing projection of one Choreography event-flow step.

    Choreography owns semantic order/participants. This object only answers which
    authored event phase the current visual should express during its Story-owned
    activation window. It never changes timing or final geometry.
    """

    event_id: str
    event_order: int | None
    stage: EventFlowStage
    step_index: int
    focus_asset_id: str | None
    source_asset_id: str | None
    target_asset_id: str | None
    result_asset_id: str | None
    relationship: str | None
    semantic_action: str | None
    authority: str
    involvement: str
    progression_type: str | None = None
    handoff_mode: str = "NONE"
    incoming_from_asset_id: str | None = None
    handoff_to_event_ids: tuple[str, ...] = ()
    handoff_to_asset_ids: tuple[str, ...] = ()
    handoff_to_event_id: str | None = None
    handoff_to_asset_id: str | None = None
    trigger_char_start: int | None = None
    trigger_char_end: int | None = None
    spoken_start: float | None = None
    spoken_end: float | None = None
    phase_chain: tuple[MotionEventPhase, ...] = ()
    relation_only: bool = False

    def to_payload(self) -> dict[str, object | None]:
        return {
            "event_id": self.event_id,
            "event_order": self.event_order,
            "stage": self.stage.value,
            "step_index": self.step_index,
            "focus_asset_id": self.focus_asset_id,
            "source_asset_id": self.source_asset_id,
            "target_asset_id": self.target_asset_id,
            "result_asset_id": self.result_asset_id,
            "relationship": self.relationship,
            "semantic_action": self.semantic_action,
            "authority": self.authority,
            "involvement": self.involvement,
            "progression_type": self.progression_type,
            "handoff_mode": self.handoff_mode,
            "incoming_from_asset_id": self.incoming_from_asset_id,
            "handoff_to_event_ids": list(self.handoff_to_event_ids),
            "handoff_to_asset_ids": list(self.handoff_to_asset_ids),
            "handoff_to_event_id": self.handoff_to_event_id,
            "handoff_to_asset_id": self.handoff_to_asset_id,
            "trigger_char_start": self.trigger_char_start,
            "trigger_char_end": self.trigger_char_end,
            "spoken_start": self.spoken_start,
            "spoken_end": self.spoken_end,
            "phase_chain": [phase.to_payload() for phase in self.phase_chain],
            "relation_only": self.relation_only,
        }


class MotionEventFlowResolver:
    """Bind rich Choreography event-flow plans to individual rendered visuals.

    The resolver is deliberately topic-agnostic. It consumes only semantic event
    structure authored by the Final Package/Choreography and never image content,
    scene ids, nouns, or package-specific presets.
    """

    _STAGE_PRIORITY = {
        EventFlowStage.PAYOFF: 600,
        EventFlowStage.REACT: 500,
        EventFlowStage.INTERACT: 400,
        EventFlowStage.ADD: 300,
        EventFlowStage.ESTABLISH: 200,
        EventFlowStage.RELEASE: 0,
    }

    def resolve_all(
        self,
        directive: ChoreographyDirective | None,
        asset_ids: list[str] | tuple[str, ...],
        *,
        semantic_event_by_asset: dict[str, str | None] | None = None,
    ) -> dict[str, MotionEventAssignment]:
        if directive is None or not directive.event_flows:
            return {}
        semantic_event_by_asset = semantic_event_by_asset or {}
        return {
            asset_id: assignment
            for asset_id in asset_ids
            if (assignment := self.resolve(
                directive,
                asset_id,
                semantic_event_id=semantic_event_by_asset.get(asset_id),
            )) is not None
        }

    def resolve(
        self,
        directive: ChoreographyDirective | None,
        asset_id: str,
        *,
        semantic_event_id: str | None = None,
    ) -> MotionEventAssignment | None:
        if directive is None or not directive.event_flows:
            return None

        candidates: list[tuple[int, int, int, MotionEventAssignment]] = []
        owned_phases: list[MotionEventPhase] = []

        for flow_index, flow in enumerate(directive.event_flows):
            owns_event = not semantic_event_id or flow.event_id == semantic_event_id
            incoming_from = self._incoming_focus_asset(directive, flow.event_id, asset_id)
            for step_index, step in enumerate(flow.steps):
                involvement = self._involvement_for_stage(step, asset_id)
                if involvement is None or step.stage == EventFlowStage.RELEASE:
                    continue
                # Story still owns the asset's primary semantic event. The only legal
                # cross-event participation is an explicit authored relation phase: a
                # source may INTERACT with a later event and a target may REACT to an
                # earlier event. This is required for V1.2 event dependency chains and
                # does not grant unrelated ADD/ESTABLISH/PAYOFF ownership.
                cross_event_relation = (
                    not owns_event
                    and step.authority in {
                        "FINAL_PACKAGE_ASSET_RELATION",
                        "FINAL_PACKAGE_INTERACTION_TARGET",
                    }
                    and step.stage in {EventFlowStage.INTERACT, EventFlowStage.REACT}
                    and involvement in {"SOURCE", "TARGET"}
                )
                cross_event_proxy = (
                    not owns_event
                    and step.authority in SEMANTIC_PROXY_AUTHORITIES
                    and step.stage in {
                        EventFlowStage.ESTABLISH,
                        EventFlowStage.ADD,
                        EventFlowStage.PAYOFF,
                    }
                    and involvement in {"FOCUS", "RESULT", "PARTICIPANT"}
                )
                if not owns_event and not cross_event_relation and not cross_event_proxy:
                    continue
                phase = MotionEventPhase(
                    event_id=flow.event_id,
                    event_order=flow.order,
                    stage=step.stage,
                    step_index=step_index,
                    involvement=involvement,
                    focus_asset_id=step.focus_asset_id,
                    source_asset_id=step.source_asset_id,
                    target_asset_id=step.target_asset_id,
                    result_asset_id=step.result_asset_id,
                    relationship=step.relationship,
                    semantic_action=step.semantic_action,
                    authority=step.authority,
                    trigger_char_start=step.trigger_char_start,
                    trigger_char_end=step.trigger_char_end,
                    spoken_start=step.spoken_start,
                    spoken_end=step.spoken_end,
                )
                owned_phases.append(phase)
                if not owns_event:
                    # Cross-event relation/proxy phases are executable timeline additions,
                    # never the dominant assignment that owns ENTRY/handoff metadata.
                    continue
                role_bonus = self._role_bonus(step.stage, involvement)
                candidates.append((
                    self._STAGE_PRIORITY[step.stage] + role_bonus,
                    -flow_index,
                    -step_index,
                    MotionEventAssignment(
                        event_id=flow.event_id,
                        event_order=flow.order,
                        stage=step.stage,
                        step_index=step_index,
                        focus_asset_id=step.focus_asset_id,
                        source_asset_id=step.source_asset_id,
                        target_asset_id=step.target_asset_id,
                        result_asset_id=step.result_asset_id,
                        relationship=step.relationship,
                        semantic_action=step.semantic_action,
                        authority=step.authority,
                        involvement=involvement,
                        progression_type=flow.progression_type,
                        handoff_mode=flow.handoff_mode,
                        incoming_from_asset_id=incoming_from,
                        handoff_to_event_ids=flow.handoff_to_event_ids,
                        handoff_to_asset_ids=flow.handoff_to_asset_ids,
                        handoff_to_event_id=flow.handoff_to_event_id,
                        handoff_to_asset_id=flow.handoff_to_asset_id,
                        trigger_char_start=step.trigger_char_start,
                        trigger_char_end=step.trigger_char_end,
                        spoken_start=step.spoken_start,
                        spoken_end=step.spoken_end,
                    ),
                ))

        if not candidates:
            executable_phases = [
                phase for phase in owned_phases
                if (
                    phase.authority in {
                        "FINAL_PACKAGE_ASSET_RELATION",
                        "FINAL_PACKAGE_INTERACTION_TARGET",
                    }
                    and phase.stage in {EventFlowStage.INTERACT, EventFlowStage.REACT}
                    and phase.involvement in {"SOURCE", "TARGET"}
                )
                or (
                    phase.authority in SEMANTIC_PROXY_AUTHORITIES
                    and phase.stage in {
                        EventFlowStage.ESTABLISH,
                        EventFlowStage.ADD,
                        EventFlowStage.PAYOFF,
                    }
                    and phase.involvement in {"FOCUS", "RESULT", "PARTICIPANT"}
                )
            ]
            if not executable_phases:
                return None
            dominant_phase = max(
                executable_phases,
                key=lambda phase: (
                    self._STAGE_PRIORITY[phase.stage] + self._role_bonus(
                        phase.stage, phase.involvement
                    ),
                    -(phase.event_order if phase.event_order is not None else 10_000),
                    -phase.step_index,
                ),
            )
            owner_flow = next(
                (
                    flow for flow in directive.event_flows
                    if semantic_event_id and flow.event_id == semantic_event_id
                ),
                None,
            )
            return MotionEventAssignment(
                # Preserve Story event ownership. The cross-event phase remains in
                # phase_chain and executes as a semantic segment, but it must not steal
                # ENTRY/focus/handoff ownership from the asset's authored event.
                event_id=(
                    semantic_event_id
                    or (owner_flow.event_id if owner_flow is not None else dominant_phase.event_id)
                ),
                event_order=(
                    owner_flow.order if owner_flow is not None else dominant_phase.event_order
                ),
                stage=dominant_phase.stage,
                step_index=dominant_phase.step_index,
                focus_asset_id=dominant_phase.focus_asset_id,
                source_asset_id=dominant_phase.source_asset_id,
                target_asset_id=dominant_phase.target_asset_id,
                result_asset_id=dominant_phase.result_asset_id,
                relationship=dominant_phase.relationship,
                semantic_action=dominant_phase.semantic_action,
                authority=dominant_phase.authority,
                involvement=dominant_phase.involvement,
                progression_type=(owner_flow.progression_type if owner_flow else None),
                trigger_char_start=dominant_phase.trigger_char_start,
                trigger_char_end=dominant_phase.trigger_char_end,
                spoken_start=dominant_phase.spoken_start,
                spoken_end=dominant_phase.spoken_end,
                phase_chain=tuple(owned_phases),
                relation_only=True,
            )
        dominant = max(candidates, key=lambda row: row[:3])[3]
        return MotionEventAssignment(
            event_id=dominant.event_id,
            event_order=dominant.event_order,
            stage=dominant.stage,
            step_index=dominant.step_index,
            focus_asset_id=dominant.focus_asset_id,
            source_asset_id=dominant.source_asset_id,
            target_asset_id=dominant.target_asset_id,
            result_asset_id=dominant.result_asset_id,
            relationship=dominant.relationship,
            semantic_action=dominant.semantic_action,
            authority=dominant.authority,
            involvement=dominant.involvement,
            progression_type=dominant.progression_type,
            handoff_mode=dominant.handoff_mode,
            incoming_from_asset_id=dominant.incoming_from_asset_id,
            handoff_to_event_ids=dominant.handoff_to_event_ids,
            handoff_to_asset_ids=dominant.handoff_to_asset_ids,
            handoff_to_event_id=dominant.handoff_to_event_id,
            handoff_to_asset_id=dominant.handoff_to_asset_id,
            trigger_char_start=dominant.trigger_char_start,
            trigger_char_end=dominant.trigger_char_end,
            spoken_start=dominant.spoken_start,
            spoken_end=dominant.spoken_end,
            phase_chain=tuple(owned_phases),
        )

    @staticmethod
    def _involvement_for_stage(step: EventFlowStep, asset_id: str) -> str | None:
        """Return only the participant that semantically owns this phase."""
        if step.stage == EventFlowStage.PAYOFF:
            # PAYOFF belongs only to the authored result/focus. General relation
            # participants must not receive a second celebratory accent merely because
            # they are listed as context for the relation.
            if step.result_asset_id == asset_id:
                return "RESULT"
            if step.focus_asset_id == asset_id:
                return "FOCUS"
            return None
        if step.stage == EventFlowStage.REACT:
            # REACT belongs to the target. A distinct result expresses the consequence
            # once, in PAYOFF; giving it both REACT and PAYOFF creates the exact
            # micro-motion double-hit that makes dense edits feel nervous.
            if step.target_asset_id == asset_id:
                return "TARGET"
            if step.focus_asset_id == asset_id:
                return "FOCUS"
            return None
        if step.stage == EventFlowStage.INTERACT:
            if step.source_asset_id == asset_id:
                return "SOURCE"
            if step.target_asset_id == asset_id:
                return "TARGET"
            if step.focus_asset_id == asset_id:
                return "FOCUS"
            return None
        if step.stage in {EventFlowStage.ADD, EventFlowStage.ESTABLISH}:
            if step.focus_asset_id == asset_id:
                return "FOCUS"
            if asset_id in step.participant_asset_ids:
                return "PARTICIPANT"
            return None
        return None

    @staticmethod
    def _role_bonus(stage: EventFlowStage, involvement: str) -> int:
        if stage == EventFlowStage.PAYOFF and involvement == "RESULT":
            return 50
        if stage == EventFlowStage.PAYOFF and involvement == "RESULT_MEMBER":
            return 35
        if stage == EventFlowStage.REACT and involvement in {"TARGET", "FOCUS"}:
            return 40
        if stage == EventFlowStage.INTERACT and involvement == "SOURCE":
            return 35
        if stage in {EventFlowStage.ADD, EventFlowStage.ESTABLISH} and involvement == "FOCUS":
            return 25
        return 0

    @classmethod
    def _incoming_focus_asset(
        cls,
        directive: ChoreographyDirective,
        event_id: str,
        asset_id: str,
    ) -> str | None:
        flow = next((row for row in directive.event_flows if row.event_id == event_id), None)
        if flow is None:
            return None

        # First prefer an earlier focus inside the same event. This supports a real
        # leader -> participant -> result chain without consulting unrelated events.
        path = flow.focus_path_asset_ids
        try:
            index = path.index(asset_id)
        except ValueError:
            index = -1
        if index > 0:
            return path[index - 1]

        # At an event boundary, use a predecessor only when the graph gives one
        # unambiguous visual source. Multiple predecessors are a merge, not a fake
        # single direction, so Motion abstains from choosing one arbitrarily.
        predecessors = [
            row for row in directive.event_flows
            if event_id in (
                row.handoff_to_event_ids
                or ((row.handoff_to_event_id,) if row.handoff_to_event_id else ())
            )
        ]
        sources = tuple(dict.fromkeys(
            source
            for row in predecessors
            if (source := cls._terminal_focus_asset(row))
        ))
        return sources[0] if len(sources) == 1 else None

    @staticmethod
    def _terminal_focus_asset(flow) -> str | None:
        for step in reversed(flow.steps):
            if step.stage == EventFlowStage.RELEASE:
                continue
            if step.focus_asset_id:
                return step.focus_asset_id
        if flow.result_asset_ids:
            return flow.result_asset_ids[-1]
        if flow.leader_asset_ids:
            return flow.leader_asset_ids[-1]
        return None