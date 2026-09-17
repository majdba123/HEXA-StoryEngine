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


@dataclass(frozen=True, slots=True)
class ChoreographyDirective:
    beat_id: str
    sequence_id: str
    phase: SequencePhase
    action: str
    hook: HookKind = HookKind.NONE
    hook_mechanism: HookMechanism = HookMechanism.NONE
    energy: float = 0.5
    tension: float = 0.0
    primary_asset_id: str | None = None
    interaction_asset_id: str | None = None
    actor_asset_ids: tuple[str, ...] = ()
    support_asset_ids: tuple[str, ...] = ()
    semantic_labels: tuple[str, ...] = ()
    relationship: str | None = None
    continuity_from: str | None = None
    continuity_mode: ContinuityMode = ContinuityMode.NONE
    pacing_bias: float = 1.0


@dataclass(frozen=True, slots=True)
class ChoreographySequence:
    id: str
    beat_ids: tuple[str, ...]
    start: float
    end: float
    hook: HookKind = HookKind.NONE
    hook_mechanism: HookMechanism = HookMechanism.NONE
    tension_peak: float = 0.0


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
        for sequence in self.sequences:
            if not sequence.beat_ids:
                raise ValueError("choreography sequence cannot be empty")
            if sequence.hook == HookKind.NONE and sequence.hook_mechanism != HookMechanism.NONE:
                raise ValueError("non-hook sequence cannot own a hook mechanism")
