from __future__ import annotations

from collections import defaultdict
from math import inf

from app.models import AssetActivation, StoryBeat

from .relation_contract import relation_requires_reaction
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
        result_interactions_by_event = self._assign_result_interactions(
            ordered_groups,
            event_assets,
            interactions,
        )
        reaction_asset_ids = {
            row.asset_id for row in transitions if row.meaningful
        }
        progression_type = self._progression_type(beat)

        metadata: list[dict[str, object]] = []
        for event_id, rows in ordered_groups:
            leader_units = self._role_units(rows, "LEADER")
            participant_units = self._role_units(rows, "PARTICIPANT")
            context_units = self._role_units(rows, "CONTEXT")
            authored_result_units = self._role_units(rows, "RESULT")
            result_interactions = result_interactions_by_event.get(event_id, ())
            result_units = self._relation_result_units(
                authored_result_units,
                result_interactions,
            )
            text_anchor_units = self._role_units(rows, "TEXT_ANCHOR")
            metadata.append({
                "event_id": event_id,
                "rows": rows,
                "interactions": interactions_by_event.get(event_id, ()),
                "result_interactions": result_interactions,
                "leader_units": leader_units,
                "participant_units": participant_units,
                "context_units": context_units,
                "result_units": result_units,
                "text_anchor_units": text_anchor_units,
                "leaders": self._flatten_units(leader_units),
                "participants": self._flatten_units(participant_units),
                "contexts": self._flatten_units(context_units),
                "results": self._flatten_units(result_units),
                "text_anchors": self._flatten_units(text_anchor_units),
                "dependency_ids": self._unique(
                    dependency
                    for row in rows
                    for dependency in row.semantic_event_dependency_ids
                    if dependency and dependency != event_id
                ),
            })

        dependents_by_event: dict[str, list[str]] = defaultdict(list)
        for item in metadata:
            event_id = str(item["event_id"])
            for dependency_id in item["dependency_ids"]:
                dependents_by_event[str(dependency_id)].append(event_id)

        flows: list[SemanticEventFlow] = []
        for index, item in enumerate(metadata):
            event_id = str(item["event_id"])
            rows = item["rows"]
            assert isinstance(rows, list)
            event_interactions = item["interactions"]
            payoff_interactions = item["result_interactions"]
            assert isinstance(event_interactions, tuple)
            assert isinstance(payoff_interactions, tuple)
            leader_ids = item["leaders"]
            participant_ids = item["participants"]
            context_ids = item["contexts"]
            result_ids = item["results"]
            text_anchor_ids = item["text_anchors"]
            dependency_ids = item["dependency_ids"]
            leader_units = item["leader_units"]
            participant_units = item["participant_units"]
            result_units = item["result_units"]
            assert isinstance(leader_ids, tuple)
            assert isinstance(participant_ids, tuple)
            assert isinstance(context_ids, tuple)
            assert isinstance(result_ids, tuple)
            assert isinstance(text_anchor_ids, tuple)
            assert isinstance(dependency_ids, tuple)
            assert isinstance(leader_units, tuple)
            assert isinstance(participant_units, tuple)
            assert isinstance(result_units, tuple)

            (
                handoff_mode,
                handoff_to_event_ids,
                handoff_to_asset_ids,
            ) = self._handoff_targets(
                index=index,
                metadata=metadata,
                dependents_by_event=dependents_by_event,
            )
            singular_event = handoff_to_event_ids[0] if len(handoff_to_event_ids) == 1 else None
            singular_asset = handoff_to_asset_ids[0] if len(handoff_to_asset_ids) == 1 else None

            steps = self._steps(
                leader_units=leader_units,
                participant_units=participant_units,
                result_units=result_units,
                interactions=event_interactions,
                payoff_interactions=payoff_interactions,
                reaction_asset_ids=reaction_asset_ids,
                handoff_to_asset_ids=handoff_to_asset_ids,
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
                    progression_type=progression_type,
                    handoff_mode=handoff_mode,
                    handoff_to_event_ids=handoff_to_event_ids,
                    handoff_to_asset_ids=handoff_to_asset_ids,
                    handoff_to_event_id=singular_event,
                    handoff_to_asset_id=singular_asset,
                    confidence=max((row.confidence for row in rows), default=0.0),
                    authority="FINAL_PACKAGE_SEMANTIC_EVENT",
                    evidence=self._evidence(
                        rows,
                        tuple(dict.fromkeys((*event_interactions, *payoff_interactions))),
                    ),
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
    def _assign_result_interactions(
        cls,
        ordered_groups: list[tuple[str, list[AssetActivation]]],
        event_assets: dict[str, set[str]],
        interactions: tuple[InteractionIntent, ...],
    ) -> dict[str, tuple[InteractionIntent, ...]]:
        """Route each explicit relation result to the Story event that owns the asset.

        A Final Package relation may explicitly name a result even when the package did
        not redundantly mark that visual with a RESULT event role. The relation itself
        is semantic authority, so the result still needs one PAYOFF phase. We attach
        that payoff to the result asset's existing Story event rather than moving the
        asset into the source event or inventing new timing.
        """
        assigned: dict[str, list[InteractionIntent]] = defaultdict(list)
        order_index = {event_id: index for index, (event_id, _rows) in enumerate(ordered_groups)}
        for interaction in interactions:
            if (
                not interaction.executable
                or interaction.authority not in {
                    "FINAL_PACKAGE_ASSET_RELATION",
                    "FINAL_PACKAGE_INTERACTION_TARGET",
                }
                or not interaction.result_asset_id
            ):
                continue
            owners = [
                event_id
                for event_id, assets in event_assets.items()
                if interaction.result_asset_id in assets
            ]
            if not owners:
                continue
            owner = min(owners, key=lambda event_id: order_index[event_id])
            assigned[owner].append(interaction)
        return {event_id: tuple(rows) for event_id, rows in assigned.items()}

    @staticmethod
    def _relation_result_units(
        authored_units: tuple[tuple[str, ...], ...],
        interactions: tuple[InteractionIntent, ...],
    ) -> tuple[tuple[str, ...], ...]:
        units = list(authored_units)
        represented = {asset_id for unit in units for asset_id in unit}
        for interaction in interactions:
            result_id = interaction.result_asset_id
            if result_id and result_id not in represented:
                units.append((result_id,))
                represented.add(result_id)
        return tuple(units)

    @classmethod
    def _steps(
        cls,
        *,
        leader_units: tuple[tuple[str, ...], ...],
        participant_units: tuple[tuple[str, ...], ...],
        result_units: tuple[tuple[str, ...], ...],
        interactions: tuple[InteractionIntent, ...],
        payoff_interactions: tuple[InteractionIntent, ...],
        reaction_asset_ids: set[str],
        handoff_to_asset_ids: tuple[str, ...],
    ) -> tuple[EventFlowStep, ...]:
        steps: list[EventFlowStep] = []

        # Each semantic visual unit gets its own authored focus step. If one semantic
        # intent resolves to multiple cutouts, they stay in the same step so Choreography
        # never invents internal order for a compound/multi-cutout visual.
        for unit in leader_units:
            steps.append(EventFlowStep(
                stage=EventFlowStage.ESTABLISH,
                focus_asset_id=unit[0],
                participant_asset_ids=unit,
            ))
        for unit in participant_units:
            steps.append(EventFlowStep(
                stage=EventFlowStage.ADD,
                focus_asset_id=unit[0],
                participant_asset_ids=unit,
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
                trigger_char_start=interaction.trigger_char_start,
                trigger_char_end=interaction.trigger_char_end,
                spoken_start=interaction.spoken_start,
                spoken_end=interaction.spoken_end,
            ))
            target_has_state_change = bool(
                interaction.object_asset_id
                and interaction.object_asset_id in reaction_asset_ids
            )
            if cls._should_react(interaction, target_has_state_change):
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
                    trigger_char_start=interaction.trigger_char_start,
                    trigger_char_end=interaction.trigger_char_end,
                    spoken_start=interaction.spoken_start,
                    spoken_end=interaction.spoken_end,
                ))

        for unit in result_units:
            result_id = unit[0]
            result_interaction = cls._interaction_for_result(
                result_id,
                tuple(dict.fromkeys((*interactions, *payoff_interactions))),
            )
            steps.append(EventFlowStep(
                stage=EventFlowStage.PAYOFF,
                focus_asset_id=result_id,
                participant_asset_ids=unit,
                source_asset_id=(
                    result_interaction.subject_asset_id if result_interaction else None
                ),
                target_asset_id=(
                    result_interaction.object_asset_id if result_interaction else None
                ),
                result_asset_id=result_id,
                relationship=(result_interaction.relationship if result_interaction else None),
                semantic_action=(result_interaction.semantic_action if result_interaction else None),
                authority=(
                    result_interaction.authority
                    if result_interaction
                    else "FINAL_PACKAGE_SEMANTIC_EVENT"
                ),
                trigger_char_start=(
                    result_interaction.trigger_char_start if result_interaction else None
                ),
                trigger_char_end=(
                    result_interaction.trigger_char_end if result_interaction else None
                ),
                spoken_start=(
                    result_interaction.spoken_start if result_interaction else None
                ),
                spoken_end=(
                    result_interaction.spoken_end if result_interaction else None
                ),
            ))

        if steps:
            release_focus: str | None = None
            if len(handoff_to_asset_ids) == 1:
                release_focus = handoff_to_asset_ids[0]
            elif not handoff_to_asset_ids:
                if result_units:
                    release_focus = result_units[-1][0]
                elif leader_units:
                    release_focus = leader_units[-1][0]
                elif participant_units:
                    release_focus = participant_units[-1][0]
            steps.append(EventFlowStep(
                stage=EventFlowStage.RELEASE,
                focus_asset_id=release_focus,
                participant_asset_ids=(
                    handoff_to_asset_ids
                    if handoff_to_asset_ids
                    else ((release_focus,) if release_focus else ())
                ),
            ))
        return tuple(steps)

    @classmethod
    def _should_react(
        cls,
        interaction: InteractionIntent,
        target_has_state_change: bool,
    ) -> bool:
        return relation_requires_reaction(
            semantic_action=interaction.semantic_action,
            executable=interaction.executable,
            target_asset_id=interaction.object_asset_id,
            target_has_state_change=target_has_state_change,
        )

    @staticmethod
    def _interaction_for_result(
        result_asset_id: str,
        interactions: tuple[InteractionIntent, ...],
    ) -> InteractionIntent | None:
        direct = [
            row for row in interactions
            if row.result_asset_id == result_asset_id
        ]
        if direct:
            return max(direct, key=lambda row: (row.executable, row.confidence))
        return None

    @classmethod
    def _handoff_targets(
        cls,
        *,
        index: int,
        metadata: list[dict[str, object]],
        dependents_by_event: dict[str, list[str]],
    ) -> tuple[str, tuple[str, ...], tuple[str, ...]]:
        item = metadata[index]
        event_id = str(item["event_id"])
        by_id = {str(row["event_id"]): row for row in metadata}
        direct_dependents = cls._unique(dependents_by_event.get(event_id, ()))
        if direct_dependents:
            targets = tuple(
                sorted(
                    direct_dependents,
                    key=lambda target: cls._metadata_sort_key(by_id[target]),
                )
            )
            mode = "BRANCH" if len(targets) > 1 else "DEPENDENCY"
        elif index + 1 < len(metadata):
            targets = (str(metadata[index + 1]["event_id"]),)
            mode = "SEQUENTIAL"
        else:
            return "NONE", (), ()

        assets = cls._unique(
            asset_id
            for target in targets
            for asset_id in cls._handoff_assets(by_id[target])
        )
        return mode, targets, assets

    @staticmethod
    def _metadata_sort_key(item: dict[str, object]) -> tuple[float, float, str]:
        rows = item.get("rows")
        if not isinstance(rows, list):
            return inf, inf, str(item.get("event_id") or "")
        return SemanticEventFlowPlanner._event_sort_key(
            str(item.get("event_id") or ""), rows
        )

    @staticmethod
    def _handoff_assets(item: dict[str, object]) -> tuple[str, ...]:
        # Leader is the strongest next-event visual authority, followed by result or
        # participant. Preserve a multi-cutout semantic unit together rather than taking
        # an arbitrary member.
        for key in ("leader_units", "result_units", "participant_units", "text_anchor_units"):
            units = item.get(key)
            if isinstance(units, tuple) and units:
                first = units[0]
                if isinstance(first, tuple):
                    return tuple(str(value) for value in first if value)
        return ()

    @staticmethod
    def _activation_sort_key(row: AssetActivation) -> tuple[float, int, int, str]:
        return (
            float(row.spoken_start) if row.spoken_start is not None else inf,
            int(row.sequence_order) if row.sequence_order is not None else 10_000,
            int(row.trigger_char_start) if row.trigger_char_start is not None else 10**9,
            row.asset_id,
        )

    @classmethod
    def _role_units(
        cls,
        rows: list[AssetActivation],
        role: str,
    ) -> tuple[tuple[str, ...], ...]:
        role = role.upper()
        selected = [
            row for row in rows
            if role in {value.upper() for value in row.semantic_event_roles}
        ]
        selected.sort(key=cls._activation_sort_key)
        grouped: dict[str, list[str]] = {}
        order: list[str] = []
        for row in selected:
            key = row.semantic_unit_id or row.asset_id
            if key not in grouped:
                grouped[key] = []
                order.append(key)
            if row.asset_id not in grouped[key]:
                grouped[key].append(row.asset_id)
        return tuple(tuple(grouped[key]) for key in order if grouped[key])

    @staticmethod
    def _flatten_units(units: tuple[tuple[str, ...], ...]) -> tuple[str, ...]:
        return tuple(dict.fromkeys(asset_id for unit in units for asset_id in unit))

    @staticmethod
    def _progression_type(beat: StoryBeat) -> str | None:
        context = beat.semantic_context
        if context is None:
            return None
        progression = context.scene_metadata.get("semantic_progression")
        if not isinstance(progression, dict):
            return None
        value = progression.get("type")
        return str(value) if value else None

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
