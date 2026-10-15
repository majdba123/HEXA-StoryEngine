"""Cinematic VNext2 motion correction: exits that finish, one emphasis per beat, calm pacing.

Covers the rules added after the reviewed Black Hat render: a segment starting on an
encoded frame owns that frame (no one-frame jump to the old pose), the outgoing hero's
full-frame exit yields to competing incoming arrivals, the opener hold pulse and the
PAYOFF secondary pulse never add a second emphasis leader, and the encoded-motion QA
profiles enforce the same calm arrival limits Motion plans with.
"""
from __future__ import annotations

import json
import re

import pytest

from app.boundary import SceneBoundaryPlanner
from app.models import CompositionBeat, LayoutItem, MotionCue, MotionSegment
from app.motion.arrivals import SLIDE_MAX_PEAK_SPEED, SLIDE_MIN_SECONDS, SLIDE_SECONDS
from app.motion.hero_travel import HERO_TRAVEL, HeroTravelPlanner
from app.motion.resolution import POP_MIN_SECONDS, POP_SECONDS
from app.motion.timing import REFERENCE_POP, REFERENCE_SLIDE
from app.render.motion import FFmpegMotionAdapter
from tests.visual.test_sprint_4_5_scene_handoffs import NEW_ON_OLD, Scene
from tests.visual.test_vnext2_payoff_resolution import LEFT, RIGHT, _beat
from tests.visual.test_vnext2_payoff_resolution import _cue as _payoff_cue
from tests.visual.test_vnext2_payoff_resolution import _run as _payoff_run
from tests.visual.test_vp4_hero_travel import _assets, _cue


# -- frame ownership of a segment -------------------------------------------------------------
def _evaluate(expression: str, t: float) -> float:
    env = {"lt": lambda a, b: float(a < b), "gte": lambda a, b: float(a >= b), "pow": pow,
           "between": lambda x, a, b: float(a <= x <= b), "_if": lambda c, a, b: a if c else b}
    return float(eval(re.sub(r"\bif\(", "_if(", expression), {"__builtins__": {}}, {**env, "t": t}))


@pytest.mark.parametrize("frame", [59, 61, 62, 89])
def test_a_segment_starting_on_an_encoded_frame_owns_that_frame(frame: int) -> None:
    start = frame / 30                                    # 6-decimal text may round past the frame
    pop = MotionSegment(phase="PAYOFF", start=start, end=start + 0.3, program={"keyframes": [
        {"progress": 0.0, "scale": 0.84, "easing": "smoothstep"}, {"progress": 1.0, "scale": 1.0}]})
    cue = MotionCue(beat_id="b", asset_id="a", kind="program_v3", start=start, end=start + 0.3,
                    params={"engine_version": 3}, segments=[pop])
    expression = FFmpegMotionAdapter().scale_expression(cue=cue, segment_start=0.0, segment_duration=5.0)
    assert _evaluate(expression, frame / 30) == pytest.approx(0.84)          # never the full-size pose
    assert _evaluate(expression, (frame + 9) / 30) == pytest.approx(1.0)
    values = [_evaluate(expression, (frame + k) / 30) for k in range(10)]
    assert all(b >= a - 1e-9 for a, b in zip(values, values[1:]))           # monotonic, no jump


# -- the outgoing hero's full-frame exit ------------------------------------------------------
def _hero_exit_scene(later: int | None, *, faint_opener: bool = False) -> Scene:
    scene = Scene(lead=16, opener=NEW_ON_OLD, later=later, opener_opacity=faint_opener)
    scene.story[0] = scene.story[0].model_copy(update={
        "active_visual_semantic_state": {"old_a": "old_a", "old_b": "old_b"}})
    scene.motion = [c.model_copy(update={"params": {**c.params, "scene_hero": True}})
                    if (c.beat_id, c.asset_id) == ("b1", "old_b") else c for c in scene.motion]
    return scene


def test_the_hero_exit_yields_to_incoming_arrivals_while_it_would_still_be_leaving() -> None:
    planner = SceneBoundaryPlanner(horizontal_padding=0.0952)
    alone = _hero_exit_scene(later=None).plan(planner)
    assert alone.audit["hero_exit"] == "full_frame_exit"
    spec = alone.overlap_exits["old_b"]
    exit_frames = round((spec["end"] - spec["start"]) * 30)
    busy = _hero_exit_scene(later=16 + exit_frames // 2).plan(planner)      # a reveal mid-exit
    assert busy.overlap_exits == {}
    assert "incoming_arrivals_during_exit" in busy.audit["hero_exit"]
    after = _hero_exit_scene(later=16 + exit_frames + 2).plan(planner)      # a reveal after it left
    assert after.audit["hero_exit"] == "full_frame_exit"


def test_a_faint_opener_keeps_the_leaving_hero_as_cover_so_no_frame_turns_near_white() -> None:
    planner = SceneBoundaryPlanner(horizontal_padding=0.0952)
    alone = _hero_exit_scene(later=None, faint_opener=True).plan(planner)
    spec = alone.overlap_exits["old_b"]
    exit_frames = round((spec["end"] - spec["start"]) * 30)
    busy = _hero_exit_scene(later=16 + exit_frames // 2, faint_opener=True).plan(planner)
    assert busy.audit["hero_exit"] == "full_frame_exit" and set(busy.overlap_exits) == {"old_b"}


# -- one emphasis leader per beat -------------------------------------------------------------
def test_the_opener_hold_pulse_never_adds_a_second_emphasis_leader() -> None:
    support = _cue("support", 0.1, 0.35)
    pulse = MotionSegment(phase="ESTABLISH", start=2.0, end=2.9, semantic_action="HERO_EMPHASIS",
                          program={"keyframes": [{"progress": 0.0, "scale": 1.0}, {"progress": 0.35, "scale": 1.05},
                                                 {"progress": 0.65, "scale": 1.05}, {"progress": 1.0, "scale": 1.0}]})
    hero = _cue("hero", 1.6, 1.8, segments=[pulse])
    hero = hero.model_copy(update={"params": {**hero.params, "hero_emphasis": {"start": 2.0, "end": 2.9,
                                                                               "scale": 1.05}}})
    from tests.visual.test_vp4_hero_travel import HERO, SUPPORT, _beat as _travel_beat
    beat = _travel_beat(end=4.0)
    planner = HeroTravelPlanner()
    out = planner.hold_emphasis(story=[beat], composition=[CompositionBeat(beat_id="b", items=[SUPPORT, HERO])],
                                motion=[support, hero], assets=_assets("support", "hero"))
    assert planner.hold_decisions == [{"beat_id": "b", "asset_id": "support",
                                       "decision": "beat_already_has_emphasis_leader"}]
    assert out == [support, hero]


def test_a_payoff_subject_gets_no_secondary_pulse_when_another_asset_already_leads() -> None:
    calls = []

    def emphasize(**kwargs):
        calls.append(kwargs["cue"].asset_id)
        return None, "abstain:test"

    late = LayoutItem(asset_id="late", x=0.5, y=0.85, width=0.1, height=0.1, z=2)
    leader = _payoff_cue("late", 1.6, 1.9, hero_emphasis={"start": 2.1, "end": 2.6, "scale": 1.04})
    director, _ = _payoff_run([_payoff_cue("support", 0.2, 0.5), _payoff_cue("result", 1.0, 1.3), leader],
                              [_beat()], {"b": [LEFT, RIGHT, late]}, emphasize=emphasize)
    decision = director.decisions[0]
    assert decision.wash == "none" and decision.priority in {"P0", "P1", "P2"}
    assert decision.pulse == "abstain:beat_has_emphasis_leader" and calls == []


# -- calm pacing contract ---------------------------------------------------------------------
def test_encoded_qa_enforces_the_same_calm_limits_motion_plans_with() -> None:
    assert REFERENCE_SLIDE.max_normalized_speed == SLIDE_MAX_PEAK_SPEED <= 0.6
    assert (REFERENCE_SLIDE.minimum_seconds, REFERENCE_SLIDE.target_seconds) == (SLIDE_MIN_SECONDS, SLIDE_SECONDS)
    assert (REFERENCE_POP.minimum_seconds, REFERENCE_POP.target_seconds) == (POP_MIN_SECONDS, POP_SECONDS)
    assert HERO_TRAVEL.max_normalized_speed <= 1.0 and HERO_TRAVEL.minimum_seconds >= 0.40


def test_planned_programs_stay_json_round_trippable() -> None:
    cue = _cue("hero", 1.0, 1.3)
    assert json.loads(cue.model_dump_json())["params"]["program"]["keyframes"][0]["scale"] == 1.0
