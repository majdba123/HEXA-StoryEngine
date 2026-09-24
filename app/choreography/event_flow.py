from __future__ import annotations

from collections import defaultdict
from math import inf

from app.models import AssetActivation, StoryBeat

from .models import (
    EventFlowStage,
    EventFlowStep,
    InteractionIntent,
    SemanticEventFlow,
    VisualStateTransition,
)


class SemanticEventFlowPlanner:
    """Compile Final Package 1.2 semantic events into visual mini-story contracts.

    Story has already resolved authored semantic intents to real extracted asset ids and
    narration windows. Choreography consumes that authority rather than re-inferring
    meaning from pixels or topic vocabulary. The resulting flow describes WHAT should
    happen inside one semantic event; Motion remains responsible for HOW it moves.
    """

    _PACKAGE_SOURCE = "final_package_semantic_binding"

    def compile(
        self,
        *,
        beat: StoryBeat,
        interactions: tuple[InteractionIntent, ...],
        transitions: tuple[VisualStateTransition, ...],
    ) -> tuple[SemanticEventFlow, ...]:
        groups: dict[str, list[AssetActivation]] = defaultdict(list)
        renderable_ids = set(beat.primary_asset_ids + beat.support_asset_ids)
        for activation in beat.asset_activations:
            if (
                activation.source != self._PACKAGE_SOURCE
                or activation.policy == "FALLBACK"
                or not activation.semantic_event_id
                or activation.asset_id not in renderable_ids
            ):
                continue
            groups[activation.semantic_event_id].append(activation)

        if not groups:
            return ()

        ordered_groups = sorted(
            groups.items(),
            key=lambda item: self._event_sort_key(item[0], item[1]),
        )
        event_assets = {
            event_id: {row.asset_id for row in rows}
            for event_id, rows in ordered_groups
        }
        interactions_by_event = self._assign_interactions(
            ordered_groups,
            event_assets,
            interactions,
        )
        transitions_by_asset = {row.asset_id: row for row in transitions if row.meaningful}

        metadata: list[dict[str, object]] = []
        for event_id, rows in ordered_groups:
            metadata.append({
                "event_id": event_id,
                "rows": rows,
                "interactions": interactions_by_event.get(event_id, ()),
                "leaders": self._assets_for_role(rows, "LEADER"),
                "participants": self._assets_for_role(rows, "PARTICIPANT"),
                "contexts": self._assets_for_role(rows, "CONTEXT"),
                "results": self._assets_for_role(rows, "RESULT"),
                "text_anchors": self._assets_for_role(rows, "TEXT_ANCHOR"),
                "dependency_ids": self._unique(
                    dependency
                    for row in rows
                    for dependency in row.semantic_event_dependency_ids
                    if dependency and dependency != event_id
                ),
            })

        flows: list[SemanticEventFlow] = []
        for index, item in enumerate(metadata):
            event_id = str(item["event_id"])
            rows = item["rows"]
            assert isinstance(rows, list)
            event_interactions = item["interactions"]
            assert isinstance(event_interactions, tuple)
            leader_ids = item["leaders"]
            participant_ids = item["participants"]
            context_ids = item["contexts"]
            result_ids = item["results"]
            text_anchor_ids = item["text_anchors"]
            dependency_ids = item["dependency_ids"]
            assert isinstance(leader_ids, tuple)
            assert isinstance(participant_ids, tuple)
            assert isinstance(context_ids, tuple)
            assert isinstance(result_ids, tuple)
            assert isinstance(text_anchor_ids, tuple)
            assert isinstance(dependency_ids, tuple)

            next_item = metadata[index + 1] if index + 1 < len(metadata) else None
            handoff_to_event_id: str | None = None
            handoff_to_asset_id: str | None = None
            if next_item is not None:
                handoff_to_event_id = str(next_item["event_id"])
                handoff_to_asset_id = self._handoff_asset(next_item)

            flow_asset_ids = set(event_assets[event_id])
            has_meaningful_reaction = any(
                asset_id in transitions_by_asset for asset_id in flow_asset_ids
            )
            steps = self._steps(
                leaders=leader_ids,
                participants=participant_ids,
                results=result_ids,
                interactions=event_interactions,
                has_meaningful_reaction=has_meaningful_reaction,
                handoff_to_asset_id=handoff_to_asset_id,
            )
            stages = tuple(dict.fromkeys(step.stage for step in steps))
            flows.append(
                SemanticEventFlow(
                    event_id=event_id,
                    order=self._event_order(rows),
                    dependency_ids=dependency_ids,
                    leader_asset_ids=leader_ids,
                    participant_asset_ids=participant_ids,
                    context_asset_ids=context_ids,
                    result_asset_ids=result_ids,
                    text_anchor_asset_ids=text_anchor_ids,
                    interactions=event_interactions,
                    stages=stages,
                    steps=steps,
                    handoff_to_event_id=handoff_to_event_id,
                    handoff_to_asset_id=handoff_to_asset_id,
                    confidence=max((row.confidence for row in rows), default=0.0),
                    authority="FINAL_PACKAGE_SEMANTIC_EVENT",
                    evidence=self._evidence(rows, event_interactions),
                )
            )
        return tuple(flows)

    @staticmethod
    def _event_sort_key(
        event_id: str,
        rows: list[AssetActivation],
    ) -> tuple[float, float, str]:
        order = min(
            (float(row.semantic_event_order) for row in rows if row.semantic_event_order is not None),
            default=inf,
        )
        spoken = min(
            (float(row.spoken_start) for row in rows if row.spoken_start is not None),
            default=inf,
        )
        return order, spoken, event_id

    @staticmethod
    def _event_order(rows: list[AssetActivation]) -> int | None:
        values = [row.semantic_event_order for row in rows if row.semantic_event_order is not None]
        return min(values) if values else None

    @classmethod
    def _assign_interactions(
        cls,
        ordered_groups: list[tuple[str, list[AssetActivation]]],
        event_assets: dict[str, set[str]],
        interactions: tuple[InteractionIntent, ...],
    ) -> dict[str, tuple[InteractionIntent, ...]]:
        assigned: dict[str, list[InteractionIntent]] = defaultdict(list)
        order_index = {event_id: index for index, (event_id, _rows) in enumerate(ordered_groups)}

        for interaction in interactions:
            # Only authored package interactions are allowed to shape an event flow.
            # Fallback relations remain available on the directive but cannot invent an
            # interaction phase that the Final Package never authored.
            if interaction.authority not in {
                "FINAL_PACKAGE_ASSET_RELATION",
                "FINAL_PACKAGE_INTERACTION_TARGET",
            }:
                continue
            best_event: str | None = None
            best_score = 0
            for event_id, assets in event_assets.items():
                score = 0
                if interaction.subject_asset_id in assets:
                    score += 4
                if interaction.object_asset_id in assets:
                    score += 4
                if interaction.result_asset_id in assets:
                    score += 2
                if score > best_score or (
                    score == best_score
                    and score > 0
                    and best_event is not None
                    and order_index[event_id] < order_index[best_event]
                ):
                    best_event = event_id
                    best_score = score
            if best_event is not None and best_score > 0:
                assigned[best_event].append(interaction)

        return {event_id: tuple(rows) for event_id, rows in assigned.items()}

    @classmethod
    def _steps(
        cls,
        *,
        leaders: tuple[str, ...],
        participants: tuple[str, ...],
        results: tuple[str, ...],
        interactions: tuple[InteractionIntent, ...],
        has_meaningful_reaction: bool,
        handoff_to_asset_id: str | None,
    ) -> tuple[EventFlowStep, ...]:
        steps: list[EventFlowStep] = []
        if leaders:
            steps.append(EventFlowStep(
                stage=EventFlowStage.ESTABLISH,
                focus_asset_id=leaders[0],
                participant_asset_ids=leaders,
            ))
        if participants:
            steps.append(EventFlowStep(
                stage=EventFlowStage.ADD,
                focus_asset_id=participants[0],
                participant_asset_ids=participants,
            ))

        for interaction in interactions:
            if not interaction.executable:
                continue
            interaction_assets = cls._unique((
                interaction.subject_asset_id,
                interaction.object_asset_id,
                interaction.result_asset_id,
            ))
            steps.append(EventFlowStep(
                stage=EventFlowStage.INTERACT,
                focus_asset_id=(
                    interaction.subject_asset_id
                    or interaction.object_asset_id
                    or interaction.result_asset_id
                ),
                participant_asset_ids=interaction_assets,
                source_asset_id=interaction.subject_asset_id,
                target_asset_id=interaction.object_asset_id,
                result_asset_id=interaction.result_asset_id,
                relationship=interaction.relationship,
                semantic_action=interaction.semantic_action,
                authority=interaction.authority,
            ))
            if interaction.requires_state_change or has_meaningful_reaction:
                steps.append(EventFlowStep(
                    stage=EventFlowStage.REACT,
                    focus_asset_id=(
                        interaction.object_asset_id
                        or interaction.result_asset_id
                        or interaction.subject_asset_id
                    ),
                    participant_asset_ids=interaction_assets,
                    source_asset_id=interaction.subject_asset_id,
                    target_asset_id=interaction.object_asset_id,
                    result_asset_id=interaction.result_asset_id,
                    relationship=interaction.relationship,
                    semantic_action=interaction.semantic_action,
                    authority=interaction.authority,
                ))

        if results:
            steps.append(EventFlowStep(
                stage=EventFlowStage.PAYOFF,
                focus_asset_id=results[0],
                participant_asset_ids=results,
                result_asset_id=results[0],
            ))

        if steps:
            release_focus = handoff_to_asset_id
            if release_focus is None:
                release_focus = (
                    results[0] if results else
                    leaders[0] if leaders else
                    participants[-1] if participants else
                    None
                )
            steps.append(EventFlowStep(
                stage=EventFlowStage.RELEASE,
                focus_asset_id=release_focus,
                participant_asset_ids=(release_focus,) if release_focus else (),
            ))
        return tuple(steps)

    @classmethod
    def _handoff_asset(cls, item: dict[str, object]) -> str | None:
        for key in ("leaders", "results", "participants", "text_anchors"):
            values = item.get(key)
            if isinstance(values, tuple) and values:
                return str(values[0])
        return None

    @staticmethod
    def _assets_for_role(
        rows: list[AssetActivation],
        role: str,
    ) -> tuple[str, ...]:
        role = role.upper()
        return SemanticEventFlowPlanner._unique(
            row.asset_id
            for row in rows
            if role in {value.upper() for value in row.semantic_event_roles}
        )

    @staticmethod
    def _evidence(
        rows: list[AssetActivation],
        interactions: tuple[InteractionIntent, ...],
    ) -> tuple[str, ...]:
        evidence = ["final_package_semantic_event"]
        if any("LEADER" in {role.upper() for role in row.semantic_event_roles} for row in rows):
            evidence.append("final_package_event_leader")
        if any("RESULT" in {role.upper() for role in row.semantic_event_roles} for row in rows):
            evidence.append("final_package_event_result")
        if interactions:
            evidence.append("final_package_event_relation")
        if any(row.semantic_event_dependency_ids for row in rows):
            evidence.append("final_package_event_dependency")
        return tuple(evidence)

    @staticmethod
    def _unique(values) -> tuple[str, ...]:
        return tuple(dict.fromkeys(value for value in values if value))
