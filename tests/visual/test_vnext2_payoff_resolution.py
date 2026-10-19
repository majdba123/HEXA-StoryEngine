"""Cinematic VNext2 PAYOFF resolution: the resolving subject arrives with the reference
pop and, when safe and spaced, the established backdrop recedes (blur + grey wash).

Story instants never move; every wash rule fails closed with an exact reason.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.models import CompositionBeat, LayoutItem, MotionCue, MotionSegment, StoryBeat, StoryEventAuthority, VisualAsset
from app.motion.resolution import (
    POP_MAX_GROWTH,
    POP_START_SCALE,
    REFERENCE_WASH,
    WASH_MIN_GAP_SECONDS,
    PayoffResolutionDirector,
)
from app.motion.timing import REFERENCE_POP

_STATIC = {"name": "static_reveal_x", "settle_progress": 1.0, "keyframes": [
    {"progress": 0.0, "dx": 0.0, "dy": 0.0, "scale": 1.0},
    {"progress": 1.0, "dx": 0.0, "dy": 0.0, "scale": 1.0}]}


def _cue(asset: str, start: float, end: float, *, beat: str = "b", segments=(), **params) -> MotionCue:
    return MotionCue(beat_id=beat, asset_id=asset, kind="program_v3", start=start, end=end, segments=list(segments),
                     params={"program": json.loads(json.dumps(_STATIC)), "engine_version": 3,
                             "semantic_continuity": {"mode": "ENTER"},
                             "entry_opacity": {"initial": 0.14, "start": start, "settle": end}, **params})


def _beat(beat: str = "b", start: float = 0.0, end: float = 3.0, results=("result",), **event) -> StoryBeat:
    authority = StoryEventAuthority(event_id=f"{beat}-E1", leader_asset_ids=list(results),
                                    result_asset_ids=list(results), **event)
    return StoryBeat(id=beat, scene_id=f"s{beat}", start=start, end=end, narration="x", action="REVEAL",
                     event_authorities=[authority])


def _assets(*ids: str) -> list[VisualAsset]:
    return [VisualAsset(id=a, scene_id="s", role="supporting", image_path=Path(f"{a}.png"),
                        extraction_method="test") for a in ids]


LEFT = LayoutItem(asset_id="support", x=0.25, y=0.40, width=0.22, height=0.30, z=0)
RIGHT = LayoutItem(asset_id="result", x=0.72, y=0.55, width=0.22, height=0.32, z=1)


def _run(cues, beats, items_by_beat, *, emphasize=None):
    director = PayoffResolutionDirector()
    out = director.plan(story=beats, composition=[CompositionBeat(beat_id=b, items=i) for b, i in items_by_beat.items()],
                        motion=cues, assets=_assets(*{c.asset_id for c in cues}), emphasize=emphasize)
    return director, {(c.beat_id, c.asset_id): c for c in out}


def test_build_up_resolution_recedes_the_backdrop_and_pops_the_result() -> None:
    cues = [_cue("support", 0.2, 0.5), _cue("result", 1.0, 1.3)]
    director, out = _run(cues, [_beat()], {"b": [LEFT, RIGHT]})
    decision = director.decisions[0]
    assert (decision.case, decision.priority, decision.wash) == ("BUILD_UP", "P0", REFERENCE_WASH.name)
    result = out[("b", "result")]
    wash = result.params["focus_wash"]
    assert wash["focus_asset_ids"] == ["result"] and wash["start"] == pytest.approx(1.0)
    assert wash["end"] == 3.0 and wash["blur_px"] > 0 and 0 < wash["tint_alpha"] < 1
    # Story instants are unchanged; the pop rests at 1.0 before the Story settle.
    assert (result.start, result.end) == (1.0, 1.3)
    frames = result.params["program"]["keyframes"]
    assert frames[0]["scale"] >= POP_START_SCALE - 1e-9 and frames[-1]["scale"] == 1.0
    seconds = result.params["reference_pop"]["seconds"]
    assert (1 - frames[0]["scale"]) * RIGHT.height / seconds <= POP_MAX_GROWTH + 1e-6
    assert REFERENCE_POP.max_normalized_speed == POP_MAX_GROWTH


def test_nothing_on_screen_before_the_result_means_nothing_to_recede() -> None:
    director, out = _run([_cue("result", 0.1, 0.4), _cue("support", 0.1, 0.4)], [_beat()], {"b": [LEFT, RIGHT]})
    assert director.decisions[0].case == "OPENING" and director.decisions[0].wash == "none"
    assert "focus_wash" not in out[("b", "result")].params


def test_a_later_reveal_keeps_the_backdrop_crisp() -> None:
    director, _ = _run([_cue("support", 0.2, 0.5), _cue("result", 1.0, 1.3), _cue("late", 1.6, 1.9)],
                       [_beat()], {"b": [LEFT, RIGHT, LayoutItem(asset_id="late", x=0.5, y=0.85, width=0.1, height=0.1)]})
    assert "wash:backdrop_reveals_after_result" in director.decisions[0].reasons


def test_a_result_on_the_final_word_gets_its_arrival_only() -> None:
    director, out = _run([_cue("support", 0.2, 0.5), _cue("result", 2.6, 2.8)], [_beat()], {"b": [LEFT, RIGHT]})
    decision = director.decisions[0]
    assert (decision.case, decision.priority, decision.wash) == ("SHORT_FINAL", "P3", "none")
    assert "focus_wash" not in out[("b", "result")].params
    assert out[("b", "result")].params["reference_pop"]["profile"] == "REFERENCE_POP"


def test_a_backdrop_asset_drawn_above_an_overlapping_focus_blocks_the_wash() -> None:
    over = LayoutItem(asset_id="support", x=0.68, y=0.55, width=0.22, height=0.30, z=5)
    director, _ = _run([_cue("support", 0.2, 0.5), _cue("result", 1.0, 1.3)], [_beat()], {"b": [over, RIGHT]})
    assert "wash:backdrop_above_focus" in director.decisions[0].reasons


def test_a_backdrop_asset_that_continues_into_the_next_scene_blocks_the_wash() -> None:
    beats = [_beat("b"), _beat("c", 3.0, 6.0, results=())]
    cues = [_cue("support", 0.2, 0.5), _cue("result", 1.0, 1.3),
            _cue("support", 3.0, 3.3, beat="c", semantic_continuity={"mode": "PERSIST"})]
    director, _ = _run(cues, beats, {"b": [LEFT, RIGHT], "c": [LEFT]})
    assert "wash:backdrop_continues_into_next_scene" in director.decisions[0].reasons


def test_washes_keep_the_reference_spacing_and_the_stronger_one_wins() -> None:
    beats = [_beat("b", 0.0, 3.0), _beat("c", 3.0, 6.0)]
    other = LayoutItem(asset_id="other", x=0.25, y=0.75, width=0.2, height=0.2, z=0)
    cues = [_cue("support", 0.2, 0.5), _cue("result", 1.0, 1.3),
            _cue("support", 3.2, 3.5, beat="c"), _cue("other", 3.3, 3.6, beat="c"), _cue("result", 4.0, 4.3, beat="c")]
    director, out = _run(cues, beats, {"b": [LEFT, RIGHT], "c": [LEFT, other, RIGHT]})
    assert WASH_MIN_GAP_SECONDS > 3.0
    washed = [d.beat_id for d in director.decisions if d.wash != "none"]
    assert washed == ["c"]                                    # two receding units beat one
    assert "wash:reference_spacing" in director.decisions[0].reasons


def test_a_pop_never_fights_a_relation_segment_and_payoff_accents_carry_the_pop() -> None:
    relation = MotionSegment(phase="INTERACT", start=1.0, end=1.3, program=_STATIC, source_asset_id="support",
                             target_asset_id="result", relationship="CAUSES")
    director, out = _run([_cue("support", 0.2, 0.5), _cue("result", 1.0, 1.3, segments=[relation])],
                         [_beat()], {"b": [LEFT, RIGHT]})
    assert director.decisions[0].arrival.startswith("kept:")
    payoff = MotionSegment(phase="PAYOFF", start=1.0, end=1.25, program={"name": "reference_result_enter", "keyframes": [
        {"progress": 0.0, "dx": 0.0, "dy": 0.0, "scale": 1.0}, {"progress": 0.6, "dx": 0.0, "dy": 0.0, "scale": 1.04},
        {"progress": 1.0, "dx": 0.0, "dy": 0.0, "scale": 1.0}]}, involvement="RESULT")
    _, out = _run([_cue("support", 0.2, 0.5), _cue("result", 1.0, 1.3, segments=[payoff])], [_beat()], {"b": [LEFT, RIGHT]})
    row = out[("b", "result")].segments[0]
    assert row.phase == "PAYOFF" and (row.start, row.end) == (1.0, 1.25)   # phase and window kept
    assert row.program["name"] == "reference_pop_payoff" and row.program["keyframes"][0]["scale"] < 1.0


_PULSE = {"name": "reference_result_enter", "keyframes": [
    {"progress": 0.0, "dx": 0.0, "dy": 0.0, "scale": 1.0}, {"progress": 0.6, "dx": -0.008, "dy": 0.01, "scale": 1.034},
    {"progress": 1.0, "dx": 0.0, "dy": 0.0, "scale": 1.0}]}


def test_a_target_that_reacts_with_its_reveal_arrives_with_the_reference_pop() -> None:
    """C4 / reference G6 (real Black Hat beat-005 chip): a result whose REACT starts with its
    reveal used to fade in at full size under a 1.03 out-and-back pulse. The reaction is its
    arrival: REACT and PAYOFF both carry one pop (grow into place, then still), same phases,
    same windows, same relation fields."""
    react = MotionSegment(phase="REACT", start=1.0, end=1.29, program=_PULSE, source_asset_id="support",
                          target_asset_id="result", relationship="ENABLES", involvement="TARGET")
    payoff = MotionSegment(phase="PAYOFF", start=1.0, end=1.29, program=_PULSE, involvement="RESULT")
    # The real chip's Composition box (0.38 W x 0.54 H): its pop is judged as an entrance
    # (REFERENCE_POP), like the PAYOFF it shares the window with, not as an in-place accent.
    chip = LayoutItem(asset_id="result", x=0.43, y=0.30, width=0.38, height=0.54, z=1)
    director, out = _run([_cue("support", 0.2, 0.5), _cue("result", 1.0, 1.29, segments=[react, payoff])],
                         [_beat()], {"b": [LEFT, chip]})
    rows = {row.phase: row for row in out[("b", "result")].segments}
    for phase, before in (("REACT", react), ("PAYOFF", payoff)):
        row = rows[phase]
        assert (row.start, row.end) == (before.start, before.end)
        frames = row.program["keyframes"]
        assert frames[0]["scale"] < 1.0 and frames[-1]["scale"] == 1.0          # grows into place
        assert max(frame["scale"] for frame in frames) <= 1.0 + POP_MAX_GROWTH  # no held pulse
    assert rows["REACT"].relationship == "ENABLES" and rows["REACT"].source_asset_id == "support"
    assert rows["REACT"].program["keyframes"] == rows["PAYOFF"].program["keyframes"]  # one gesture


def test_a_reaction_after_the_reveal_still_owns_its_motion() -> None:
    react = MotionSegment(phase="REACT", start=1.1, end=1.29, program=_PULSE, source_asset_id="support",
                          target_asset_id="result", relationship="ENABLES", involvement="TARGET")
    director, out = _run([_cue("support", 0.2, 0.5), _cue("result", 1.0, 1.29, segments=[react])],
                         [_beat()], {"b": [LEFT, RIGHT]})
    assert director.decisions[0].arrival.startswith("kept:")
    assert out[("b", "result")].segments[0].program == _PULSE


def test_secondary_pulse_goes_to_a_resolved_subject_without_a_wash() -> None:
    calls = []

    def emphasize(**kwargs):
        calls.append(kwargs["cue"].asset_id)
        return None, "abstain:test"

    director, _ = _run([_cue("support", 0.2, 0.5), _cue("result", 2.6, 2.8)], [_beat()], {"b": [LEFT, RIGHT]},
                       emphasize=emphasize)
    assert director.decisions[0].pulse == "none"                # P3: no pulse attempt
    director, _ = _run([_cue("support", 0.2, 0.5), _cue("result", 1.0, 1.3)], [_beat()], {"b": [LEFT, RIGHT]},
                       emphasize=emphasize)
    assert calls == [] and director.decisions[0].wash != "none"  # the wash is the focus
