"""Reference grammar: a subject at rest stays still; emphasis is carried by other tools.

Full-length review of the approved references (2026-10-20, docs/reference-motion-grammar.md
G18): no element that is already on screen is nudged sideways, dipped or pulsed in place.
Emphasis comes from arrival (whip/slide/pop), the grey wash with background defocus, the
drawn arrow and the large keyword. Here, the last Motion pass turns every in-place
out-and-back accent (rest -> offset/scale -> rest) of an INTERACT / REACT / PAYOFF /
ESTABLISH segment into a deliberate still segment. Phase, window, relation fields and the
semantic event stay exactly as authored, so Text, Boundary, connections and QA keep reading
the same story; only the micro gesture is gone. Arrivals (programs that start away from
rest) are untouched.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.models import MotionCue, MotionSegment

STILL_PHASES = frozenset({"INTERACT", "REACT", "PAYOFF", "ESTABLISH"})
STILL_PREFIX = "reference_still_"
_EPS = 1e-9


def _at_rest(frame: dict) -> bool:
    return (abs(float(frame.get("dx", 0.0))) <= _EPS and abs(float(frame.get("dy", 0.0))) <= _EPS
            and abs(float(frame.get("scale", 1.0)) - 1.0) <= _EPS)


def is_out_and_back(program: dict | None) -> bool:
    frames = (program or {}).get("keyframes")
    if not isinstance(frames, list) or len(frames) < 3:
        return False
    return _at_rest(frames[0]) and _at_rest(frames[-1]) and not all(_at_rest(row) for row in frames)


def still_program(program: dict, phase: str) -> dict:
    return {
        **{key: value for key, value in program.items() if key != "semantic_active_duration"},
        "name": f"{STILL_PREFIX}{phase.lower()}",
        "settle_progress": 1.0,
        "stilled_from": str(program.get("name") or ""),
        "keyframes": [
            {"progress": 0.0, "dx": 0.0, "dy": 0.0, "scale": 1.0, "easing": "linear"},
            {"progress": 1.0, "dx": 0.0, "dy": 0.0, "scale": 1.0, "easing": "linear"},
        ],
    }


def is_reference_still(program: dict | None) -> bool:
    """A deliberate still accent: named so, with identity keyframes only."""
    frames = (program or {}).get("keyframes") or []
    return (str((program or {}).get("name") or "").startswith(STILL_PREFIX)
            and all(_at_rest(row) for row in frames))


@dataclass(frozen=True, slots=True)
class StillDecision:
    beat_id: str
    asset_id: str
    phase: str
    replaced: str


class ReferenceStillnessPolicy:
    def __init__(self) -> None:
        self.decisions: list[StillDecision] = []

    def apply(self, motion: list[MotionCue]) -> list[MotionCue]:
        self.decisions = []
        output: list[MotionCue] = []
        for cue in motion:
            segments: list[MotionSegment] = []
            changed = False
            for row in cue.segments:
                if row.phase in STILL_PHASES and is_out_and_back(row.program):
                    self.decisions.append(StillDecision(cue.beat_id, cue.asset_id, row.phase,
                                                        str(row.program.get("name") or "")))
                    row = row.model_copy(update={"program": still_program(row.program, row.phase)})
                    changed = True
                segments.append(row)
            output.append(cue.model_copy(update={"segments": segments}) if changed else cue)
        return output
