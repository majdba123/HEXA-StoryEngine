from __future__ import annotations

from app.models import StoryBeat

from .interactions import is_connectable_relation
from .models import (
    InteractionIntent,
    RelationFlowDecision,
    RelationTreatment,
    SemanticEventFlow,
)

AUTHORED_RELATION_AUTHORITIES = frozenset({
    "FINAL_PACKAGE_ASSET_RELATION",
    "FINAL_PACKAGE_INTERACTION_TARGET",
})


def plan_relation_flow(
    beat: StoryBeat,
    interactions: tuple[InteractionIntent, ...],
    event_flows: tuple[SemanticEventFlow, ...],
) -> tuple[RelationFlowDecision, ...]:
    """Choose the smallest visual treatment for each authored relation in one beat.

    Evidence only: an authored relation, its direction (the Sprint 4.1 directional
    allowlist, shared with connectors), and the authored event order and leadership.
    A focus handoff is chosen only when the target leads a strictly later authored event
    the source does not take part in; everything else keeps the existing expression or
    abstains. Timing stays Story-owned: Motion anchors the handoff to the target's reveal.
    """
    visible = set(beat.primary_asset_ids) | set(beat.support_asset_ids)
    position = {flow.event_id: index for index, flow in enumerate(event_flows)}
    decisions: list[RelationFlowDecision] = []
    relations = {
        (row.subject_asset_id or "", row.object_asset_id or "", row.relationship or ""): row
        for row in interactions
        if row.authority in AUTHORED_RELATION_AUTHORITIES
    }
    for key in sorted(relations):
        row = relations[key]
        source, target = row.subject_asset_id, row.object_asset_id

        def decide(treatment: RelationTreatment, reason: str, **events: str | None):
            decisions.append(RelationFlowDecision(
                relationship=row.relationship,
                source_asset_id=source,
                target_asset_id=target,
                treatment=treatment,
                reason=reason,
                **events,
            ))

        if not row.executable:
            decide(RelationTreatment.ABSTAIN, "non_executable_relation")
            continue
        if not source or not target or source == target:
            decide(RelationTreatment.ABSTAIN, "ambiguous_direction")
            continue
        if source not in visible or target not in visible:
            decide(RelationTreatment.ABSTAIN, "missing_carrier")
            continue
        if not is_connectable_relation(row.relationship):
            decide(RelationTreatment.ABSTAIN, "non_directional_relation")
            continue
        source_flows = [flow for flow in event_flows if source in flow.asset_ids]
        target_flows = [flow for flow in event_flows if target in flow.leader_asset_ids]
        if not source_flows or not target_flows:
            decide(RelationTreatment.INTERACTION, "target_not_authored_leader")
            continue
        source_flow = min(source_flows, key=lambda flow: position[flow.event_id])
        later = [
            flow for flow in target_flows
            if position[flow.event_id] > position[source_flow.event_id]
        ]
        if not later:
            decide(
                RelationTreatment.INTERACTION, "co_present_event",
                source_event_id=source_flow.event_id,
            )
            continue
        target_flow = min(later, key=lambda flow: position[flow.event_id])
        if source in target_flow.asset_ids:
            decide(
                RelationTreatment.INTERACTION, "source_active_in_target_event",
                source_event_id=source_flow.event_id, target_event_id=target_flow.event_id,
            )
            continue
        decide(
            RelationTreatment.FOCUS_HANDOFF, "authored_directional_event_progression",
            source_event_id=source_flow.event_id, target_event_id=target_flow.event_id,
        )
    return tuple(decisions)
