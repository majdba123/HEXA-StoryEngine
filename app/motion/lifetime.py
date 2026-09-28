from __future__ import annotations

from dataclasses import dataclass

from app.choreography import ChoreographyDirective, EventFlowStage
from app.models import StoryBeat
from app.motion.event_flow import MotionEventAssignment
from app.motion.timing import story_activation_window


@dataclass(frozen=True, slots=True)
class SemanticLifetimeDecision:
    """Scene-local authority keeping one exact runtime visual past event handoffs."""

    asset_id: str
    owner_event_id: str
    keep_visible_through: float
    release_deadline: float
    future_event_ids: tuple[str, ...]
    reasons: tuple[str, ...]


class SemanticVisualLifetimeIndex:
    """Resolve exact-asset semantic lifetime from Story + Choreography authority.

    This index never merges visually similar assets and never infers identity from pixels,
    names, or scene-specific rules.  When Story supplies semantic Scene state, entry is
    monotonic for the remainder of that Scene: event dependencies, focus, and reuse may
    shape motion, but absence of such evidence may not retire an entered visual.
    """

    def __init__(self, decisions: dict[str, SemanticLifetimeDecision]) -> None:
        self._decisions = decisions

    def for_asset(self, asset_id: str) -> SemanticLifetimeDecision | None:
        return self._decisions.get(asset_id)

    @classmethod
    def build(
        cls,
        *,
        beat: StoryBeat,
        directive: ChoreographyDirective | None,
        assignments: dict[str, MotionEventAssignment],
    ) -> "SemanticVisualLifetimeIndex":
        if directive is None or not directive.event_flows or not assignments:
            return cls({})

        flows = {flow.event_id: flow for flow in directive.event_flows}
        successors: dict[str, set[str]] = {event_id: set() for event_id in flows}
        for flow in directive.event_flows:
            for target in flow.handoff_to_event_ids:
                if target in flows and target != flow.event_id:
                    successors[flow.event_id].add(target)
            if flow.handoff_to_event_id and flow.handoff_to_event_id in flows:
                successors[flow.event_id].add(flow.handoff_to_event_id)
            for dependency in flow.dependency_ids:
                if dependency in flows and dependency != flow.event_id:
                    successors[dependency].add(flow.event_id)

        event_windows = cls._event_windows(beat, directive)
        owner_events_by_asset = cls._owner_events_by_asset(beat)
        decisions: dict[str, SemanticLifetimeDecision] = {}

        for asset_id, assignment in assignments.items():
            if not assignment.event_id or assignment.event_id not in flows:
                continue
            if (
                beat.active_visual_semantic_state is not None
                and asset_id in beat.active_visual_semantic_state
            ):
                event_ids = [flow.event_id for flow in directive.event_flows]
                owner_index = event_ids.index(assignment.event_id)
                decisions[asset_id] = SemanticLifetimeDecision(
                    asset_id=asset_id,
                    owner_event_id=assignment.event_id,
                    keep_visible_through=float(beat.end),
                    release_deadline=float(beat.end),
                    future_event_ids=tuple(event_ids[owner_index + 1:]),
                    reasons=("scene_active_until_scene_end",),
                )
                continue
            reachable = cls._reachable_events(assignment.event_id, successors)
            if not reachable:
                continue

            keep_until = 0.0
            reasons: list[str] = []
            future_events: set[str] = set()

            # Exact same runtime asset explicitly participates in a later event.
            for event_id in reachable:
                flow = flows[event_id]
                if cls._flow_references_asset(flow, asset_id):
                    event_end = event_windows.get(event_id, (0.0, 0.0))[1]
                    if event_end > keep_until:
                        keep_until = event_end
                    future_events.add(event_id)
                    reasons.append(f"future_event:{event_id}")

            # Story can reuse the exact carrier through a later semantic activation/proxy.
            for event_id in owner_events_by_asset.get(asset_id, ()):
                if event_id not in reachable:
                    continue
                event_end = event_windows.get(event_id, (0.0, 0.0))[1]
                if event_end > keep_until:
                    keep_until = event_end
                future_events.add(event_id)
                reasons.append(f"story_reuse:{event_id}")

            # A relation authored in the current event can still require this carrier
            # while its exact counterpart belongs to a later dependent event. This is
            # the generic SCENE_014 class: old program -> later calendar/result.
            for phase in assignment.phase_chain:
                if phase.stage not in {
                    EventFlowStage.INTERACT,
                    EventFlowStage.REACT,
                    EventFlowStage.PAYOFF,
                }:
                    continue
                # Relation-counterpart inference is intentionally stricter than exact
                # asset reuse. A later target/result does not mean every causal source
                # must stay on screen. Only an authored persistence action proves that
                # this carrier itself must remain visible through the later counterpart.
                # Other relation families need independent future-use evidence above.
                if str(phase.semantic_action or "").upper() != "LOOP":
                    continue
                if asset_id not in {
                    phase.focus_asset_id,
                    phase.source_asset_id,
                    phase.target_asset_id,
                    phase.result_asset_id,
                }:
                    continue
                counterpart_ids = {
                    candidate
                    for candidate in (
                        phase.source_asset_id,
                        phase.target_asset_id,
                        phase.result_asset_id,
                    )
                    if candidate and candidate != asset_id
                }
                for counterpart_id in counterpart_ids:
                    for event_id in owner_events_by_asset.get(counterpart_id, ()):
                        if event_id not in reachable:
                            continue
                        event_end = event_windows.get(event_id, (0.0, 0.0))[1]
                        if event_end > keep_until:
                            keep_until = event_end
                        future_events.add(event_id)
                        reasons.append(
                            f"relation_counterpart:{counterpart_id}:{event_id}"
                        )

            if keep_until <= 0.0:
                continue
            keep_until = min(float(beat.end), keep_until)
            release_deadline = cls._release_deadline(
                beat=beat,
                event_windows=event_windows,
                keep_visible_through=keep_until,
            )
            decisions[asset_id] = SemanticLifetimeDecision(
                asset_id=asset_id,
                owner_event_id=assignment.event_id,
                keep_visible_through=keep_until,
                release_deadline=release_deadline,
                future_event_ids=tuple(sorted(future_events)),
                reasons=tuple(dict.fromkeys(reasons)),
            )

        return cls(decisions)

    @staticmethod
    def _owner_events_by_asset(beat: StoryBeat) -> dict[str, set[str]]:
        output: dict[str, set[str]] = {}
        for activation in beat.asset_activations:
            if activation.semantic_event_id:
                output.setdefault(activation.asset_id, set()).add(
                    activation.semantic_event_id
                )
        for proxy in beat.semantic_event_proxies:
            output.setdefault(proxy.asset_id, set()).add(proxy.semantic_event_id)
        return output

    @staticmethod
    def _event_windows(
        beat: StoryBeat,
        directive: ChoreographyDirective,
    ) -> dict[str, tuple[float, float]]:
        starts: dict[str, list[float]] = {}
        ends: dict[str, list[float]] = {}

        for activation in beat.asset_activations:
            event_id = activation.semantic_event_id
            if not event_id:
                continue
            has_v2, window = story_activation_window(activation, beat)
            if has_v2 and window is not None:
                starts.setdefault(event_id, []).append(float(window.reveal_start))
                ends.setdefault(event_id, []).append(float(window.settle_at))
            else:
                if activation.spoken_start is not None:
                    starts.setdefault(event_id, []).append(float(activation.spoken_start))
                if activation.spoken_end is not None:
                    ends.setdefault(event_id, []).append(float(activation.spoken_end))

        for proxy in beat.semantic_event_proxies:
            starts.setdefault(proxy.semantic_event_id, []).append(float(proxy.reveal_start))
            ends.setdefault(proxy.semantic_event_id, []).append(float(proxy.settle_at))

        for flow in directive.event_flows:
            for step in flow.steps:
                start = step.reveal_start if step.reveal_start is not None else step.spoken_start
                end = step.settle_at if step.settle_at is not None else step.spoken_end
                if start is not None:
                    starts.setdefault(flow.event_id, []).append(float(start))
                if end is not None:
                    ends.setdefault(flow.event_id, []).append(float(end))

        return {
            flow.event_id: (
                min(starts.get(flow.event_id, [float(beat.start)])),
                max(ends.get(flow.event_id, [float(beat.end)])),
            )
            for flow in directive.event_flows
        }

    @staticmethod
    def _reachable_events(
        event_id: str,
        successors: dict[str, set[str]],
    ) -> set[str]:
        seen: set[str] = set()
        pending = list(successors.get(event_id, ()))
        while pending:
            current = pending.pop()
            if current in seen:
                continue
            seen.add(current)
            pending.extend(successors.get(current, ()))
        return seen

    @staticmethod
    def _flow_references_asset(flow, asset_id: str) -> bool:
        if asset_id in flow.asset_ids:
            return True
        return any(
            asset_id
            in {
                step.focus_asset_id,
                step.source_asset_id,
                step.target_asset_id,
                step.result_asset_id,
                *step.participant_asset_ids,
            }
            for step in flow.steps
        )

    @staticmethod
    def _release_deadline(
        *,
        beat: StoryBeat,
        event_windows: dict[str, tuple[float, float]],
        keep_visible_through: float,
    ) -> float:
        later_starts = [
            start
            for start, _end in event_windows.values()
            if start > keep_visible_through + 1e-6
        ]
        return min(later_starts, default=float(beat.end))
