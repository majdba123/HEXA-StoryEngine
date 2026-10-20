"""Elements interact on screen when the narration states their relation (user direction
2026-10-20; references A 16.3-16.9 s: the arrow from the character is drawn, then the cross
lands at its tip; A 60 s gear -> vault).

For every authored, directional causal relation of a beat (Final Package asset relation,
``CONNECTABLE_RELATIONS``) with both ends in the scene:

* cause first (the usual case: the effect is revealed after the cause): the relation arrow
  writes on during the ``ARROW_SECONDS`` before the effect appears (never before the cause
  has settled), the cause pulses as the arrow starts, and the effect lands at the tip;
* effect first, or both together: the arrow is drawn once both have settled; the cause
  pulses as it starts and the effect answers when the head arrives.

``interaction_schedule`` is the single timing authority: Motion adds the pulses (through
the shared, contract-validated ``pulse_at``) and the renderer draws the arrow from the same
schedule. Nothing is inferred beyond the package's own relations; Story instants are kept.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.choreography.interactions import is_connectable_relation
from app.models import CompositionBeat, MotionCue, StoryBeat, VisualAsset

from .spoken_pulse import PULSE_MIN_DELAY, pulse_at, settled_at

ARROW_SECONDS = 8 / 30    # the relation arrow's write-on (reference G5)
_EPS = 1e-6


@dataclass(frozen=True, slots=True)
class Interaction:
    source: str
    target: str
    kind: str
    arrow_start: float              # absolute seconds
    source_pulse: float | None      # absolute seconds, None: its arrival carries it
    target_pulse: float | None


@dataclass(frozen=True, slots=True)
class InteractionDecision:
    beat_id: str
    source_asset_id: str
    target_asset_id: str
    kind: str
    arrow_start: float
    source: str
    target: str


def interaction_schedule(beat: StoryBeat, cues: dict[str, MotionCue]) -> list[Interaction]:
    """The beat's relation interactions, from its Story relations and final Motion."""
    context = beat.semantic_context
    if context is None:
        return []
    asset_of: dict[str, str] = {}
    for row in sorted(beat.asset_activations, key=lambda r: r.asset_id):
        if row.semantic_unit_id and row.asset_id in cues:
            asset_of.setdefault(row.semantic_unit_id, row.asset_id)
    seen: set[tuple[str, str]] = set()
    schedule: list[Interaction] = []
    for relation in sorted(context.relations, key=lambda r: (r.spoken_start or 0.0, r.source_unit_id)):
        if not relation.causal or not is_connectable_relation(relation.kind):
            continue
        source, target = asset_of.get(relation.source_unit_id), asset_of.get(relation.target_unit_id)
        if not source or not target or source == target or (source, target) in seen:
            continue
        seen.add((source, target))
        source_settled, target_settled = settled_at(cues[source]), settled_at(cues[target])
        target_reveal = float(cues[target].start)
        if source_settled <= target_reveal - _EPS:
            start = max(source_settled + PULSE_MIN_DELAY, target_reveal - ARROW_SECONDS)
            schedule.append(Interaction(source, target, str(relation.kind).upper(), start, start, None))
        else:
            start = max(source_settled, target_settled) + PULSE_MIN_DELAY
            schedule.append(Interaction(source, target, str(relation.kind).upper(), start, start,
                                        start + ARROW_SECONDS))
    return schedule


class RelationInteractionPolicy:
    def __init__(self) -> None:
        self.decisions: list[InteractionDecision] = []

    def apply(
        self, *, story: list[StoryBeat], composition: list[CompositionBeat], motion: list[MotionCue],
        assets: list[VisualAsset],
    ) -> list[MotionCue]:
        self.decisions = []
        assets_by_id = {asset.id: asset for asset in assets}
        layouts = {row.beat_id: {item.asset_id: item for item in row.items} for row in composition}
        output = list(motion)
        index = {(cue.beat_id, cue.asset_id): position for position, cue in enumerate(output)}
        for beat in story:
            cues = {cue.asset_id: cue for cue in output if cue.beat_id == beat.id}
            for row in interaction_schedule(beat, cues):
                outcome = {}
                for role, asset_id, when in (("source", row.source, row.source_pulse),
                                             ("target", row.target, row.target_pulse)):
                    if when is None:
                        outcome[role] = "lands_at_the_arrow_tip"
                        continue
                    position = index[(beat.id, asset_id)]
                    pulsed, why = pulse_at(output[position], at=when, beat=beat,
                                           item=layouts.get(beat.id, {}).get(asset_id),
                                           beat_cues=[cue for cue in output if cue.beat_id == beat.id],
                                           assets_by_id=assets_by_id,
                                           action="INTERACT" if role == "source" else "REACT")
                    outcome[role] = why
                    if pulsed is not None:
                        output[position] = pulsed
                self.decisions.append(InteractionDecision(beat.id, row.source, row.target, row.kind,
                                                          round(row.arrow_start, 3), outcome["source"],
                                                          outcome["target"]))
        return output
