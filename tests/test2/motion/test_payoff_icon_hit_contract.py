"""PAYOFF replacements may never hand the renderer a program encoded QA will reject.

PayoffResolutionDirector replaces the PAYOFF accent that starts with a result's reveal by
one icon hit (or the reference pop). Every committed replacement must satisfy the shared
segment contract (readability floor of its window, comfort ceiling); when neither fits,
the Planner's validated program stays. Package-independent, small to large assets.
"""
from __future__ import annotations

import pytest

from app.models import CompositionBeat, LayoutItem, MotionSegment
from app.motion.contract import accent_readability_floor, segment_contract_violations
from app.motion.resolution import ICON_HIT_MAX_PEAK_SCALE, ICON_HIT_PEAK_SCALE, PayoffResolutionDirector
from tests.visual.test_vnext2_payoff_resolution import _assets, _beat, _cue

SUPPORT = LayoutItem(asset_id="support", x=0.16, y=0.80, width=0.14, height=0.14, z=0)


def _result_item(extent: float) -> LayoutItem:
    return LayoutItem(asset_id="result", x=0.55, y=0.42, width=extent, height=extent * 1.08, z=1)


def _planner_payoff(item: LayoutItem, start: float, duration: float) -> MotionSegment:
    """A Planner-shaped PAYOFF (upward lift at the golden peak) that meets its floor."""
    floor = accent_readability_floor("PAYOFF", segment_duration=duration, active_duration=duration,
                                     item_width=item.width, item_height=item.height)
    program = {"name": "reference_result_enter", "settle_progress": 1.0, "semantic_active_duration": duration,
               "keyframes": [{"progress": 0.0, "dx": 0.0, "dy": 0.0, "scale": 1.0},
                             {"progress": 0.618034, "dx": 0.0, "dy": -round(floor * 1.001, 6), "scale": 1.0},
                             {"progress": 1.0, "dx": 0.0, "dy": 0.0, "scale": 1.0}]}
    return MotionSegment(phase="PAYOFF", start=start, end=start + duration, program=program,
                         result_asset_id="result")


def _resolve(item: LayoutItem, duration: float):
    payoff = _planner_payoff(item, 1.0, duration)
    cues = [_cue("support", 0.2, 0.5), _cue("result", 1.0, 1.0 + duration, segments=[payoff])]
    director = PayoffResolutionDirector(icon_focus_mode=True)
    out = director.plan(story=[_beat()], composition=[CompositionBeat(beat_id="b", items=[SUPPORT, item])],
                        motion=cues, assets=_assets("support", "result"))
    result = next(row for row in out if row.asset_id == "result")
    return director.decisions[0], payoff, result, next(row for row in result.segments if row.phase == "PAYOFF")


def _violations(result, segment, item):
    return segment_contract_violations(phase="PAYOFF", program=segment.program, params=result.params,
                                       segment_duration=segment.end - segment.start,
                                       item_width=item.width, item_height=item.height)


@pytest.mark.parametrize("extent", [0.10, 0.16977, 0.30])
@pytest.mark.parametrize("duration", [0.30, 0.31895, 0.42, 0.80])
def test_every_committed_payoff_satisfies_the_shared_contract(extent: float, duration: float) -> None:
    item = _result_item(extent)
    decision, before, result, payoff = _resolve(item, duration)
    assert _violations(result, payoff, item) == []
    assert (payoff.start, payoff.end) == (before.start, before.end), "Story-owned PAYOFF window"
    assert (result.start, result.end) == (1.0, 1.0 + duration)
    if "payoff_icon_hit" in result.params:
        frames = payoff.program["keyframes"]
        peak = max(row["scale"] for row in frames)
        assert ICON_HIT_PEAK_SCALE <= peak <= ICON_HIT_MAX_PEAK_SCALE
        assert all(row["dx"] == row["dy"] == 0.0 for row in frames)
        assert [row["scale"] for row in frames].count(peak) == 2, "one held peak"
    else:
        # The hit abstained with an exact reason; the reference pop or the Planner kept it.
        assert any("icon_hit_" in reason for reason in decision.reasons) or decision.arrival.startswith("kept:")


def test_real_scene_36_geometry_gets_a_held_hit_that_reaches_its_floor() -> None:
    item = LayoutItem(asset_id="result", x=0.51614, y=0.24283, width=0.169766, height=0.183847, z=1)
    _decision, _before, result, payoff = _resolve(item, 0.318947)
    frames = payoff.program["keyframes"]
    peak = max(row["scale"] for row in frames)
    assert result.params["payoff_icon_hit"]["peak_scale"] == pytest.approx(peak)
    assert (peak - 1.0) * item.width >= 0.01340 - 1e-9
    assert peak <= ICON_HIT_MAX_PEAK_SCALE
    assert _violations(result, payoff, item) == []


def test_long_payoff_window_does_not_get_an_unreadable_icon_hit() -> None:
    item = _result_item(0.17)
    decision, _before, result, payoff = _resolve(item, 0.80)
    assert "payoff_icon_hit" not in result.params
    assert any(reason.endswith("icon_hit_below_readability_floor") for reason in decision.reasons)
    assert payoff.program["name"] == "reference_pop_payoff"
    assert _violations(result, payoff, item) == []


def test_infeasible_replacement_keeps_the_planner_validated_payoff() -> None:
    # A 0.12 icon: the pop reaches 0.0192 < 0.020 floor and a hit would need ~1.17.
    item = LayoutItem(asset_id="result", x=0.55, y=0.42, width=0.12, height=0.12, z=1)
    decision, before, result, payoff = _resolve(item, 0.60)
    assert decision.arrival.startswith("kept:contract_motion_below_perceptual_floor")
    assert "icon_hit_below_readability_floor" in decision.arrival
    assert payoff.program == before.program, "no replacement: Planner's valid program stays"
    assert "reference_pop" not in result.params and "payoff_icon_hit" not in result.params
    assert _violations(result, payoff, item) == []


def test_held_hit_yields_to_an_existing_emphasis_pulse_and_payoff_stays_readable() -> None:
    """Script Kiddie beat-021 (old code): a hit beside another family's growing pulse was
    flattened by EmphasisLeaderPolicy into a fully static PAYOFF (activity 0.00000)."""
    from app.motion.emphasis_leader import EmphasisLeaderPolicy

    item = LayoutItem(asset_id="result", x=0.51614, y=0.24283, width=0.169766, height=0.183847, z=1)
    payoff = _planner_payoff(item, 1.0, 0.318947)
    pulse = MotionSegment(phase="ESTABLISH", start=0.6, end=0.9, semantic_action="HERO_EMPHASIS", program={
        "name": "hero_emphasis", "settle_progress": 1.0, "keyframes": [
            {"progress": 0.0, "dx": 0.0, "dy": 0.0, "scale": 1.0},
            {"progress": 0.5, "dx": 0.0, "dy": 0.0, "scale": 1.05},
            {"progress": 1.0, "dx": 0.0, "dy": 0.0, "scale": 1.0}]})
    cues = [_cue("support", 0.2, 0.5, segments=[pulse], scene_hero=True, hero_emphasis={"peak": 1.05}),
            _cue("result", 1.0, 1.318947, segments=[payoff])]
    composition = [CompositionBeat(beat_id="b", items=[SUPPORT, item])]
    director = PayoffResolutionDirector(icon_focus_mode=True)
    motion = director.plan(story=[_beat()], composition=composition, motion=cues,
                           assets=_assets("support", "result"))
    assert "icon_hit:beat_has_emphasis_pulse" in director.decisions[0].reasons
    motion = EmphasisLeaderPolicy().plan(story=[_beat()], composition=composition, motion=motion,
                                         assets=_assets("support", "result"))
    result = next(row for row in motion if row.asset_id == "result")
    final = next(row for row in result.segments if row.phase == "PAYOFF")
    assert "payoff_icon_hit" not in result.params
    assert _violations(result, final, item) == [], "the PAYOFF survives the leader policy readable"


def test_hold_emphasis_never_adds_a_second_leader_beside_a_held_hit() -> None:
    from app.motion.hero_travel import HeroTravelPlanner

    item = LayoutItem(asset_id="result", x=0.51614, y=0.24283, width=0.169766, height=0.183847, z=1)
    _decision, _before, result, _payoff = _resolve(item, 0.318947)
    assert result.params.get("payoff_icon_hit")
    opener = _cue("support", 0.0, 0.3)
    hero = HeroTravelPlanner()
    out = hero.hold_emphasis(story=[_beat()], composition=[CompositionBeat(beat_id="b", items=[SUPPORT, item])],
                             motion=[opener, result], assets=_assets("support", "result"))
    assert hero.hold_decisions[0]["decision"] == "beat_already_has_emphasis_leader"
    assert next(row for row in out if row.asset_id == "support") == opener
