from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ReferenceGestureKind(StrEnum):
    """Approved visual gestures observed in the HEXA reference family.

    These names describe motion *shape*, not story semantics. Story/Choreography remain
    authoritative for what happens and when; Motion selects one of these bounded shapes
    to express that meaning without decorative post-settle movement.
    """

    HOLD = "HOLD"
    SLIDE_SETTLE = "SLIDE_SETTLE"
    POP_REVEAL = "POP_REVEAL"
    SEQUENTIAL_ADD = "SEQUENTIAL_ADD"
    FOCUS_HANDOFF = "FOCUS_HANDOFF"
    DIRECTIONAL_HANDOFF = "DIRECTIONAL_HANDOFF"
    SHORT_IMPACT = "SHORT_IMPACT"
    STATE_CHANGE = "STATE_CHANGE"
    RESULT_ENTER = "RESULT_ENTER"
    COMPARE_SHIFT = "COMPARE_SHIFT"


@dataclass(frozen=True, slots=True)
class ReferenceMotionLanguage:
    """Production motion-language constants derived from the approved references.

    The key invariant is one semantic gesture followed by a clean hold. Values are
    intentionally conservative; timing windows remain owned by Story/MotionTimingPolicy.
    """

    entry_settle_progress: float = 0.78
    semantic_settle_progress: float = 0.72
    max_entry_offset: float = 0.075
    max_semantic_offset: float = 0.055
    max_focus_scale: float = 1.04
    max_impact_scale: float = 1.035
    max_result_scale: float = 1.045
    support_scale_start: float = 0.975
    result_scale_start: float = 0.955

    @classmethod
    def production(cls) -> "ReferenceMotionLanguage":
        return cls()
