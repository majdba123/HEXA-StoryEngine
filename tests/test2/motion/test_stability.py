from __future__ import annotations

from app.models import MotionCue, MotionSegment
from app.motion.stability import remove_micro_reversals


def _program(dx: float, *, scale: float = 1.0, name: str = "small_return") -> dict:
    return {"name": name, "keyframes": [
        {"progress": 0.0, "dx": 0.0, "dy": 0.0, "scale": 1.0},
        {"progress": 0.5, "dx": dx, "dy": -0.005, "scale": scale},
        {"progress": 1.0, "dx": 0.0, "dy": 0.0, "scale": 1.0},
    ]}


def _cue(program: dict, *, seconds: float = 0.12, phase: str | None = None) -> MotionCue:
    segments = ([MotionSegment(phase=phase, start=1.0, end=1.0 + seconds,
                               program=program, semantic_action="PAYOFF")]
                if phase else [])
    return MotionCue(beat_id="beat", asset_id="person", kind="program_v3", start=1.0,
                     end=1.0 + seconds, params={"engine_version": 3, "program": program},
                     segments=segments)


def test_short_returning_jog_is_removed_from_base_entry_and_semantic_segment() -> None:
    base = _cue(_program(0.005))  # 9.6 px right, 5.4 px up, then back in four frames.
    payoff = _cue(_program(0.005), phase="PAYOFF")
    fixed_base, fixed_payoff = remove_micro_reversals([base, payoff], width=1920, height=1080)
    for program in (fixed_base.params["program"], fixed_payoff.segments[0].program):
        assert program["micro_reversal_removed"] is True
        assert all(row["dx"] == row["dy"] == 0.0 for row in program["keyframes"])
        assert program["name"].startswith("reference_still_")
    assert fixed_payoff.segments[0].semantic_action == "PAYOFF"
    assert (fixed_payoff.start, fixed_payoff.end) == (payoff.start, payoff.end)
    assert base.params["program"] == _program(0.005)  # source data is untouched


def test_scale_pulse_keeps_its_peak_while_its_tiny_sideways_jog_is_removed() -> None:
    cue = _cue(_program(0.005, scale=1.08, name="reference_spoken_pulse"), phase="ESTABLISH")
    fixed = remove_micro_reversals([cue], width=1920, height=1080)[0]
    program = fixed.segments[0].program
    assert [row["scale"] for row in program["keyframes"]] == [1.0, 1.08, 1.0]
    assert [row["dx"] for row in program["keyframes"]] == [0.0, 0.0, 0.0]
    assert program["name"] == "reference_spoken_pulse"


def test_meaningful_payoff_and_arrival_are_not_changed() -> None:
    large = _cue(_program(0.025), phase="PAYOFF")  # 48 px, readable movement.
    slow = _cue(_program(0.005), seconds=0.6, phase="PAYOFF")
    arrival_program = {"name": "entry", "keyframes": [
        {"progress": 0.0, "dx": -0.04, "dy": 0.0, "scale": 1.0},
        {"progress": 0.5, "dx": -0.02, "dy": 0.0, "scale": 1.0},
        {"progress": 1.0, "dx": 0.0, "dy": 0.0, "scale": 1.0}]}
    arrival = _cue(arrival_program, phase="ENTRY")
    cues = [large, slow, arrival]
    assert remove_micro_reversals(cues, width=1920, height=1080) == cues


def test_short_jog_inside_long_hold_is_removed_without_changing_hold_length() -> None:
    program = {"name": "long_hold", "keyframes": [
        {"progress": 0.0, "dx": 0.0, "dy": 0.0, "scale": 1.0},
        {"progress": 0.4, "dx": 0.0, "dy": 0.0, "scale": 1.0},
        {"progress": 0.45, "dx": 0.005, "dy": 0.0, "scale": 1.0},
        {"progress": 0.5, "dx": 0.0, "dy": 0.0, "scale": 1.0},
        {"progress": 1.0, "dx": 0.0, "dy": 0.0, "scale": 1.0},
    ]}
    cue = _cue(program, seconds=1.0, phase="ESTABLISH")
    fixed = remove_micro_reversals([cue], width=1920, height=1080)[0]
    assert fixed.segments[0].program["micro_reversal_removed"] is True
    assert fixed.segments[0].end == 2.0
