from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.models import StoryBeat
from app.motion.timing import GOLDEN_MINOR, MotionTimingPolicy

if TYPE_CHECKING:
    from app.choreography import ChoreographyPlan


MIN_FOCUS_OVERLAP_SECONDS = 2.0 / 30.0

_PACE_ORDER = ("deliberate", "balanced", "brisk", "snap")
_PACE_INDEX = {name: index for index, name in enumerate(_PACE_ORDER)}


def focus_progression_key(
    semantic_event_order: int | None,
    sequence_order: int | None,
) -> tuple[int, int]:
    """Shared semantic instant key for temporal focus arbitration.

    Explicit Final Package event/sequence order means the visuals are intentionally
    progressive even when their motion windows overlap. Only assets in the same
    authored progression lane compete for the single strongest entry accent.
    """
    return (
        int(semantic_event_order) if semantic_event_order is not None else 0,
        int(sequence_order) if sequence_order is not None else 10_000,
    )


@dataclass(frozen=True, slots=True)
class RhythmDecision:
    """Reference-calibrated temporal direction for one Story beat.

    Story remains the timing authority. This decision never invents semantic timestamps;
    it only constrains Motion's *style* inside already-authored Story windows so adjacent
    beats do not alternate between sluggish and frantic visual energy.
    """

    raw_pace_tier: str
    pace_tier: str
    minimum_read_hold: float
    accent_gap: float
    max_parallel_entry_accents: int
    smoothing_reason: str

    def to_payload(self) -> dict[str, object]:
        return {
            "raw_pace_tier": self.raw_pace_tier,
            "pace_tier": self.pace_tier,
            "minimum_read_hold_ms": round(self.minimum_read_hold * 1000),
            "accent_gap_ms": round(self.accent_gap * 1000),
            "max_parallel_entry_accents": self.max_parallel_entry_accents,
            "smoothing_reason": self.smoothing_reason,
        }


class ReferenceRhythmPolicy:
    """Shape beat-to-beat visual rhythm without overriding narration semantics.

    The accepted reference material uses fewer, more decisive accents separated by
    readable holds. Speech rate still influences the raw tier, but one unusually fast
    or slow phrase must not make the edit lurch between extremes. Hooks and explicitly
    high-tension semantic beats may keep their authored contrast.
    """

    _HOLD_SECONDS = {
        "snap": 0.16,
        "brisk": 0.20,
        "balanced": 0.25,
        "deliberate": 0.30,
    }
    _URGENT_ACTIONS = {"REJECT", "BLOCK", "LOOP"}
    _PAYOFF_ACTIONS = {"RESOLVE", "REVEAL", "PROTECT"}

    def plan(
        self,
        beats: list[StoryBeat],
        choreography: ChoreographyPlan | None,
        timing: MotionTimingPolicy,
    ) -> dict[str, RhythmDecision]:
        if not beats:
            return {}

        raw: list[str] = []
        directives = []
        for beat in beats:
            directive = choreography.for_beat(beat.id) if choreography else None
            directives.append(directive)
            raw.append(
                timing.pace_tier_for_beat(
                    beat,
                    choreography_action=directive.action if directive else None,
                    pacing_bias=directive.pacing_bias if directive else 1.0,
                )
            )

        smoothed: list[str] = []
        reasons: list[str] = []
        for index, (beat, raw_tier, directive) in enumerate(zip(beats, raw, directives)):
            raw_index = _PACE_INDEX[raw_tier]
            action = str(directive.action if directive else beat.action or "").upper()
            hook = bool(directive is not None and directive.hook.value != "NONE")
            tension = float(directive.tension) if directive is not None else 0.0

            if hook or (action in self._URGENT_ACTIONS and tension >= 0.72):
                chosen_index = raw_index
                reason = "authored_attention_contrast"
            else:
                neighborhood = [_PACE_INDEX[raw_tier]]
                if index > 0:
                    neighborhood.append(_PACE_INDEX[raw[index - 1]])
                if index + 1 < len(raw):
                    neighborhood.append(_PACE_INDEX[raw[index + 1]])
                neighborhood.sort()
                local_median = neighborhood[len(neighborhood) // 2]
                # Keep the current phrase influential while suppressing isolated spikes.
                chosen_index = round((raw_index * 2 + local_median) / 3)
                reason = "local_reference_smoothing"

            if smoothed and reason != "authored_attention_contrast":
                previous_index = _PACE_INDEX[smoothed[-1]]
                delta = chosen_index - previous_index
                if abs(delta) > 1:
                    chosen_index = previous_index + (1 if delta > 0 else -1)
                    reason = "adjacent_pace_hysteresis"

            chosen_index = max(0, min(len(_PACE_ORDER) - 1, chosen_index))
            smoothed.append(_PACE_ORDER[chosen_index])
            reasons.append(reason)

        output: dict[str, RhythmDecision] = {}
        for beat, directive, raw_tier, tier, reason in zip(
            beats, directives, raw, smoothed, reasons
        ):
            action = str(directive.action if directive else beat.action or "").upper()
            duration = max(0.08, float(beat.end) - float(beat.start))
            hold = self._HOLD_SECONDS[tier]
            if action in self._PAYOFF_ACTIONS:
                hold += 0.05
            if directive is not None and directive.phase.value == "CONSEQUENCE":
                hold += 0.04
            # A short Story beat cannot be forced to reserve a long pause. The floor is
            # intentionally modest; longer quiet periods naturally come from Story's
            # next semantic reveal rather than Motion stretching time.
            hold = min(0.36, max(0.10, min(hold, duration * 0.24)))
            accent_gap = min(0.14, max(0.06, hold * GOLDEN_MINOR))
            output[beat.id] = RhythmDecision(
                raw_pace_tier=raw_tier,
                pace_tier=tier,
                minimum_read_hold=hold,
                accent_gap=accent_gap,
                max_parallel_entry_accents=1,
                smoothing_reason=reason,
            )
        return output

    @staticmethod
    def tier_distance(left: str, right: str) -> int:
        return abs(_PACE_INDEX[str(left)] - _PACE_INDEX[str(right)])
