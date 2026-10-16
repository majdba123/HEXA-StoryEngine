"""Visual sprint Stage 5 - cause -> consequence payoff.

When a resolving result's authored relation is a directional flow/cause relation and its
event leader (another family) is already on screen, the result arrives moving away from
that cause - a short slide along the cause -> result direction, scale unchanged - instead
of the generic scale pop. Without that evidence, or without a safe path, the pop stays.
"""
from __future__ import annotations

import pytest

from app.models import LayoutItem, MotionSegment, StoryBeat, StoryEventAuthority
from app.motion.arrivals import SLIDE_DISTANCE, SLIDE_MAX_PEAK_SPEED, SMOOTHSTEP_PEAK
from app.motion.timing import REFERENCE_SLIDE
from app.render.verification import EncodedMotionVerifier
from app.targets.context import active_target
from tests.visual.test_vnext2_arrivals import _run as arrive
from tests.visual.test_vnext2_payoff_resolution import _cue, _run as resolve

CAUSE = LayoutItem(asset_id="cause", x=0.30, y=0.45, width=0.22, height=0.40, z=0)
RESULT = LayoutItem(asset_id="result", x=0.72, y=0.62, width=0.20, height=0.30, z=1)


def _beat(relation_cause: bool = True, *, leader_after: bool = False) -> StoryBeat:
    authority = StoryEventAuthority(event_id="b-E1", leader_asset_ids=["cause"], participant_asset_ids=["result"],
                                    result_asset_ids=["result"])
    return StoryBeat(id="b", scene_id="sb", start=0.0, end=3.0, narration="x", action="REVEAL",
                     event_authorities=[authority])


def _cues(relationship: str, *, cause_start: float = 0.3):
    choreography = {"relationship": relationship, "pattern": "CAUSE_EFFECT_CHAIN"}
    return [_cue("cause", cause_start, cause_start + 0.3, choreography=choreography),
            _cue("result", 1.2, 1.6, choreography=choreography)]


def _resolved(relationship: str = "ENABLES", **kw):
    _, out = resolve(_cues(relationship, **kw), [_beat()], {"b": [CAUSE, RESULT]})
    return out[("b", "result")]


@pytest.mark.parametrize("relationship", ["ENABLES", "LEADS_TO", "CAUSES", "GRANTS_ACCESS_TO"])
def test_a_directional_relation_marks_the_result_with_its_cause(relationship: str) -> None:
    result = _resolved(relationship)
    assert result.params["reference_pop"]                     # the pop stays as the fallback
    assert result.params["causal_arrival"] == {"cause_asset_id": "cause", "relationship": relationship,
                                               "event_id": "b-E1"}


@pytest.mark.parametrize("relationship", ["DECLARED_PROGRESSION", "SPECIFIES", "PERSISTS_OVER_TIME", None])
def test_without_directional_evidence_nothing_is_invented(relationship) -> None:
    assert "causal_arrival" not in _resolved(relationship or "").params


def test_a_cause_revealed_with_or_after_the_result_is_not_a_cause_on_screen() -> None:
    assert "causal_arrival" not in _resolved("ENABLES", cause_start=1.2).params


def _arrival(result_cue, items):
    cause = _cue("cause", 0.3, 0.6)
    planner, out = arrive([cause, result_cue], items)
    return planner, out["result"]


def test_the_result_arrives_moving_away_from_its_cause_without_growing() -> None:
    planner, cue = _arrival(_resolved("ENABLES"), [CAUSE, RESULT])
    decision = next(d for d in planner.decisions if d.asset_id == "result")
    assert (decision.gesture, decision.reason) == ("SLIDE", "causal_slide")
    assert "reference_pop" not in cue.params and cue.params["payoff_resolution"]["arrival"] == "causal_slide"
    target = active_target()
    slide = cue.params["reference_slide"]
    start = (slide["dx"] * target.width, slide["dy"] * target.height)
    towards_cause = ((CAUSE.x - RESULT.x) * target.width, (CAUSE.y - RESULT.y) * target.height)
    cosine = (start[0] * towards_cause[0] + start[1] * towards_cause[1]) / (
        (start[0] ** 2 + start[1] ** 2) ** 0.5 * (towards_cause[0] ** 2 + towards_cause[1] ** 2) ** 0.5)
    assert cosine == pytest.approx(1.0, abs=1e-6)              # it starts on the side of its cause
    distance = (start[0] ** 2 + start[1] ** 2) ** 0.5 / target.width
    assert distance <= SLIDE_DISTANCE + 1e-5                                  # offsets kept to 6 decimals
    assert SMOOTHSTEP_PEAK * distance / slide["seconds"] <= SLIDE_MAX_PEAK_SPEED + 1e-4
    for program in [cue.params["program"]] + [row.program for row in cue.segments]:
        assert all(frame["scale"] == 1.0 for frame in program["keyframes"])   # no enlargement
    assert (cue.start, cue.end) == (1.2, 1.6)                                  # Story instants unchanged


def test_the_payoff_segment_carries_the_slide_within_the_slide_comfort_limit() -> None:
    resolved = _resolved("ENABLES").model_copy(update={"segments": [
        MotionSegment(phase="PAYOFF", start=1.2, end=1.55, program={"name": "reference_pop_payoff", "keyframes": [
            {"progress": 0.0, "dx": 0.0, "dy": 0.0, "scale": 0.84}, {"progress": 1.0, "dx": 0.0, "dy": 0.0,
                                                                       "scale": 1.0}]})]})
    _, cue = _arrival(resolved, [CAUSE, RESULT])
    payoff = next(row for row in cue.segments if row.phase == "PAYOFF")
    assert payoff.program["name"] == "reference_slide_payoff"
    assert payoff.program["keyframes"][0]["dx"] != 0.0 and payoff.program["keyframes"][-1]["dx"] == 0.0
    speed = EncodedMotionVerifier._max_normalized_keyframe_speed(
        payoff, duration=payoff.end - payoff.start, item_width=RESULT.width, item_height=RESULT.height)
    assert speed <= REFERENCE_SLIDE.max_normalized_speed


def test_an_unsafe_path_keeps_the_pop() -> None:
    blocker = LayoutItem(asset_id="blocker", x=0.62, y=0.55, width=0.08, height=0.10, z=2)
    cause = _cue("cause", 0.3, 0.6)
    planner, out = arrive([cause, _cue("blocker", 0.4, 0.7), _resolved("ENABLES")], [CAUSE, blocker, RESULT])
    decision = next(d for d in planner.decisions if d.asset_id == "result")
    assert (decision.gesture, decision.reason) == ("POP", "payoff_resolution:causal_path_crosses_visible_asset")
    assert out["result"].params["reference_pop"]


def test_a_close_cause_limits_the_slide_to_half_the_way() -> None:
    near = LayoutItem(asset_id="cause", x=0.62, y=0.60, width=0.05, height=0.05, z=0)   # ~193 px away
    _, cue = _arrival(_resolved("ENABLES"), [near, RESULT])
    target = active_target()
    slide = cue.params["reference_slide"]
    travelled = ((slide["dx"] * target.width) ** 2 + (slide["dy"] * target.height) ** 2) ** 0.5
    span = (((RESULT.x - near.x) * target.width) ** 2 + ((RESULT.y - near.y) * target.height) ** 2) ** 0.5
    assert travelled <= 0.5 * span + 0.01 < SLIDE_DISTANCE * target.width


def test_a_cause_too_close_for_a_calm_slide_keeps_the_pop() -> None:
    touching = LayoutItem(asset_id="cause", x=0.66, y=0.58, width=0.05, height=0.05, z=0)  # ~123 px away
    planner, cue = _arrival(_resolved("ENABLES"), [touching, RESULT])
    decision = next(d for d in planner.decisions if d.asset_id == "result")
    assert (decision.gesture, decision.reason) == ("POP", "payoff_resolution:causal_cause_too_close")
    assert cue.params["reference_pop"]


def test_a_payoff_window_shorter_than_a_calm_slide_keeps_the_pop() -> None:
    short = _resolved("ENABLES").model_copy(update={"segments": [
        MotionSegment(phase="PAYOFF", start=1.2, end=1.2 + 7.5 / 30, program={"name": "reference_pop_payoff",
                      "keyframes": [{"progress": 0.0, "scale": 0.84}, {"progress": 1.0, "scale": 1.0}]})]})
    planner, cue = _arrival(short, [CAUSE, RESULT])
    decision = next(d for d in planner.decisions if d.asset_id == "result")
    assert (decision.gesture, decision.reason) == ("POP", "payoff_resolution:causal_window_below_slide_minimum")
