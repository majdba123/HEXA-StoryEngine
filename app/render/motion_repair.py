"""Repair instead of stopping when a final RenderPlan breaks the encoded-motion contract.

Pre-encode motion QA (``EncodedMotionVerifier.preflight``) proves from metadata alone that
every authored gesture reads in the encoded video: above the perceptual floor, below the
comfort ceiling, outside the encoder's dead zone. A plan that broke it used to stop the
render (PRE_ENCODE_MOTION_CONTRACT_FAILED). A render that stops helps nobody (user direction
2026-10-21), and every such finding has the answer Motion itself uses when no legal
transform fits: the element keeps its exact place, timing and opacity grammar and only the
offending gesture becomes still. An ENTRY becomes an alpha reveal (``static_reveal_*``), a
later accent a deliberate still (``reference_still_*``, grammar G18). Family layers drawn
with the repaired cue's transform get the same repair. Every output format receives the
same repairs so the formats stay one edit, QA runs again, and every repair is recorded.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from app.models import MotionCue, RenderPlan
from app.motion.family import FOLLOW_PARAM
from app.motion.stillness import still_program

PRE_ENCODE_REPAIR = True
# Encoded QA after the render: a gesture weaker than its contract in the encoded frames
# already looks still, exactly what a repaired re-encode would show; it is recorded.
ENCODED_QA_WARN = True
MAX_REPAIR_ROUNDS = 3
REPAIRED_ENTRY = "static_reveal_qa_repair"
# Arrival extras that only belong to a moving arrival.
_ARRIVAL_PARAMS = ("reference_landing", "reference_slide")
ALL_PHASES = "*"

Offender = tuple[str, str]  # (beat_id, asset_id)


def offenders(violations: Iterable[Any]) -> dict[Offender, set[str]]:
    """(beat id, asset id) -> the phases QA rejected."""
    found: dict[Offender, set[str]] = {}
    for row in violations:
        if row.beat_id and row.asset_id:
            found.setdefault((row.beat_id, row.asset_id), set()).add(str(row.phase or ALL_PHASES).upper())
    return found


def _static_entry(program: dict | None) -> dict:
    program = dict(program or {})
    frames = program.get("keyframes") or [{"progress": 0.0}, {"progress": 1.0}]
    return {
        **program,
        "name": REPAIRED_ENTRY,
        "repaired_from": str(program.get("name") or ""),
        "keyframes": [{**frame, "dx": 0.0, "dy": 0.0, "scale": 1.0} for frame in frames],
    }


def neutralize_cue(cue: MotionCue, phases: set[str]) -> MotionCue:
    """``cue`` with the gestures of ``phases`` made still (``*`` = every phase)."""
    every = ALL_PHASES in phases
    params = dict(cue.params) if isinstance(cue.params, dict) else {}
    if every or "ENTRY" in phases:
        if isinstance(params.get("program"), dict):
            params["program"] = _static_entry(params["program"])
        for key in _ARRIVAL_PARAMS:
            params.pop(key, None)
    segments = []
    for segment in cue.segments:
        if every or segment.phase in phases:
            program = (_static_entry(segment.program) if segment.phase == "ENTRY"
                       else still_program(segment.program, segment.phase))
            segment = segment.model_copy(update={"program": program})
        segments.append(segment)
    return cue.model_copy(update={"params": params, "segments": segments})


def neutralize(plan: RenderPlan, targets: dict[Offender, set[str]]) -> tuple[RenderPlan, list[dict[str, Any]]]:
    """Apply ``targets`` (and the same repair to every family follower) to ``plan``."""
    expanded = {key: set(value) for key, value in targets.items()}
    for cue in plan.motion:
        leader = cue.params.get(FOLLOW_PARAM) if isinstance(cue.params, dict) else None
        if leader and (cue.beat_id, leader) in targets:
            expanded.setdefault((cue.beat_id, cue.asset_id), set()).update(targets[(cue.beat_id, leader)])
    motion: list[MotionCue] = []
    repairs: list[dict[str, Any]] = []
    for cue in plan.motion:
        phases = expanded.get((cue.beat_id, cue.asset_id))
        if not phases:
            motion.append(cue)
            continue
        motion.append(neutralize_cue(cue, phases))
        repairs.append({
            "beat_id": cue.beat_id, "asset_id": cue.asset_id, "phases": sorted(phases),
            "repair": "still" if ALL_PHASES not in phases else "still_all_phases",
            "follower_of": cue.params.get(FOLLOW_PARAM) if (cue.beat_id, cue.asset_id) not in targets else None,
        })
    return plan.model_copy(update={"motion": motion}), repairs
