"""Cinematic VNext2 restraint: one emphasis leader per beat.

At most one Pass2 family per beat grows above its authored rest size, and only once. The
leader comes from planning authority (Sprint 4.1 character emphasis, the scene hero's
settle emphasis, another settle emphasis, else the PAYOFF subject / scene hero / semantic
focus overshoot). Everything else keeps its translation and scale-in from below.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

from app.models import CompositionBeat, LayoutItem, MotionCue, MotionSegment, StoryBeat, VisualAsset
from app.motion.emphasis_leader import EmphasisLeaderPolicy, grows

BEAT = StoryBeat(id="b", scene_id="s", start=0.0, end=4.0, narration="x", action="REVEAL")


def _overshoot(name: str = "event_chain_add_reference_pop_reveal", dx: float = 0.02) -> dict:
    return {"name": name, "settle_progress": 1.0, "keyframes": [
        {"progress": 0.0, "dx": dx, "dy": 0.0, "scale": 0.98, "easing": "ease_in_out_cubic"},
        {"progress": 0.5, "dx": dx * 0.4, "dy": 0.0, "scale": 1.0246, "easing": "ease_out_cubic"},
        {"progress": 1.0, "dx": 0.0, "dy": 0.0, "scale": 1.0, "easing": "ease_out_cubic"}]}


def _pulse(action: str, start: float, end: float, peak: float = 1.05) -> MotionSegment:
    return MotionSegment(phase="ESTABLISH", start=start, end=end, semantic_action=action, program={
        "name": "hero_settle_emphasis" if action == "HERO_EMPHASIS" else "character_emphasis",
        "keyframes": [{"progress": 0.0, "scale": 1.0}, {"progress": 0.45, "scale": peak},
                      {"progress": 1.0, "scale": 1.0}]})


def _cue(asset: str, start: float, end: float, *, segments=(), **params) -> MotionCue:
    return MotionCue(beat_id="b", asset_id=asset, kind="program_v3", start=start, end=end,
                     segments=list(segments), params={"engine_version": 3, "program": _overshoot(), **params})


def _assets(*ids: str, parent: dict | None = None) -> list[VisualAsset]:
    return [VisualAsset(id=a, scene_id="s", role="supporting", image_path=Path(f"{a}.png"), extraction_method="t",
                        parent_asset_id=(parent or {}).get(a), asset_family_id=(parent or {}).get(a))
            for a in ids]


def _run(cues, *, focus=None, assets=None):
    policy = EmphasisLeaderPolicy()
    composition = [CompositionBeat(beat_id="b", semantic_focus_asset_id=focus, items=[
        LayoutItem(asset_id=c.asset_id, x=0.2 + 0.2 * i, y=0.5, width=0.15, height=0.3)
        for i, c in enumerate(cues)])]
    out = policy.plan(story=[BEAT], composition=composition, motion=cues,
                      assets=assets or _assets(*[c.asset_id for c in cues]))
    return policy, {c.asset_id: c for c in out}


def _programs(cue: MotionCue) -> list[dict]:
    return [cue.params["program"]] + [row.program for row in cue.segments]


def _growing_assets(out: dict[str, MotionCue]) -> set[str]:
    return {asset for asset, cue in out.items() if any(grows(p) for p in _programs(cue))}


def test_only_the_hero_pulse_grows_and_supporting_overshoots_rest_at_authored_size() -> None:
    hero = _cue("hero", 0.5, 0.9, scene_hero=True, hero_emphasis={"start": 1.1, "end": 2.0, "scale": 1.05},
                segments=[MotionSegment(phase="ENTRY", start=0.5, end=0.9, program=_overshoot()),
                          _pulse("HERO_EMPHASIS", 1.1, 2.0)])
    policy, out = _run([hero, _cue("a", 0.5, 0.9), _cue("b", 0.6, 1.0)])
    assert _growing_assets(out) == {"hero"}
    # the hero's arrival no longer overshoots before its pulse: exactly one rise
    assert not grows(out["hero"].segments[0].program) and grows(out["hero"].segments[1].program)
    for asset in ("a", "b"):
        frames = out[asset].params["program"]["keyframes"]
        assert frames[0]["scale"] == 0.98 and frames[0]["dx"] == 0.02     # scale-in and travel kept
        assert max(f["scale"] for f in frames) == 1.0
    decision = policy.decisions[0]
    assert decision.leader == "hero" and decision.source == "hero_settle_emphasis"


def test_a_character_emphasis_leads_and_another_assets_settle_pulse_is_removed_with_its_carried_entry() -> None:
    character = _cue("char", 0.5, 0.9, segments=[_pulse("EMPHASIZE", 0.9, 1.4, peak=1.1)])
    other = _cue("other", 0.5, 0.9, hero_emphasis={"start": 1.0, "end": 1.9, "scale": 1.05}, segments=[
        MotionSegment(phase="ENTRY", start=0.5, end=0.9, program={**_overshoot(), "carried_for": "hero_emphasis"}),
        _pulse("HERO_EMPHASIS", 1.0, 1.9)])
    policy, out = _run([character, other])
    assert _growing_assets(out) == {"char"}
    assert out["char"].segments == character.segments                     # Sprint 4.1 untouched
    assert out["other"].segments == [] and "hero_emphasis" not in out["other"].params
    assert policy.decisions[0].removed_pulses == ("other",)


def test_a_second_character_emphasis_is_certified_and_never_removed() -> None:
    first = _cue("c1", 0.5, 0.9, segments=[_pulse("EMPHASIZE", 0.9, 1.4)])
    second = _cue("c2", 1.5, 1.9, segments=[_pulse("EMPHASIZE", 1.9, 2.4)])
    _, out = _run([first, second])
    assert out["c2"].segments[0].semantic_action == "EMPHASIZE" and grows(out["c2"].segments[0].program)


def test_without_any_pulse_the_payoff_subject_keeps_only_its_first_overshoot() -> None:
    subject = _cue("result", 1.0, 1.4, payoff_resolution={"case": "BUILD_UP"}, segments=[
        MotionSegment(phase="ENTRY", start=1.0, end=1.4, program=_overshoot()),
        MotionSegment(phase="PAYOFF", start=1.6, end=2.0, program=_overshoot("reference_result_enter"))])
    policy, out = _run([_cue("a", 0.2, 0.6), subject, _cue("b", 1.0, 1.4)], focus="a")
    assert _growing_assets(out) == {"result"}
    assert grows(out["result"].segments[0].program) and not grows(out["result"].segments[1].program)
    assert policy.decisions[0].source == "payoff_subject"


def test_semantic_focus_leads_when_nothing_else_has_authority_and_no_overshoot_means_no_leader() -> None:
    _, out = _run([_cue("a", 0.2, 0.6), _cue("focus", 0.2, 0.6)], focus="focus")
    assert _growing_assets(out) == {"focus"}
    flat = _cue("a", 0.2, 0.6)
    flat = flat.model_copy(update={"params": {**flat.params, "program": {"keyframes": [
        {"progress": 0.0, "scale": 0.9}, {"progress": 1.0, "scale": 1.0}]}}})
    policy, out = _run([flat])
    assert policy.decisions[0].leader is None and out["a"] == flat


def test_supporting_deemphasis_below_rest_is_kept() -> None:
    dip = MotionSegment(phase="ESTABLISH", start=2.0, end=2.4, semantic_action="DEEMPHASIZE", program={
        "name": "supporting_deemphasis", "keyframes": [{"progress": 0.0, "scale": 1.0},
                                                       {"progress": 0.45, "scale": 0.96},
                                                       {"progress": 1.0, "scale": 1.0}]})
    _, out = _run([_cue("lead", 0.2, 0.6, scene_hero=True), _cue("support", 0.2, 0.6, segments=[dip])])
    assert out["support"].segments[0] == dip


def test_a_pass2_family_counts_once_and_its_layers_keep_the_same_gesture() -> None:
    assets = _assets("p", "p:secondary-01", "x", parent={"p:secondary-01": "p"})
    primary = _cue("p", 0.5, 0.9, scene_hero=True)
    layer = _cue("p:secondary-01", 0.5, 0.9, family_follow="p")
    _, out = _run([primary, layer, _cue("x", 0.5, 0.9)], assets=assets)
    assert _growing_assets(out) == {"p", "p:secondary-01"}
    assert out["p"].params["program"] == out["p:secondary-01"].params["program"]


def test_inputs_are_never_mutated_or_aliased_and_the_result_is_deterministic() -> None:
    cues = [_cue("hero", 0.5, 0.9, scene_hero=True), _cue("a", 0.5, 0.9), _cue("b", 0.6, 1.0)]
    before = copy.deepcopy([c.model_dump() for c in cues])
    _, first = _run(cues)
    _, second = _run(cues)
    assert [c.model_dump() for c in cues] == before
    assert json.dumps({k: v.model_dump() for k, v in first.items()}, sort_keys=True) == \
        json.dumps({k: v.model_dump() for k, v in second.items()}, sort_keys=True)
    assert first["a"].params["program"] is not cues[1].params["program"]
    assert first["a"].params["program"]["keyframes"][1] is not cues[1].params["program"]["keyframes"][1]


def test_enforce_reapplies_the_leader_after_a_later_pass_restores_an_earlier_cue() -> None:
    cues = [_cue("hero", 0.5, 0.9, scene_hero=True), _cue("a", 0.5, 0.9)]
    policy, out = _run(cues)
    restored = [out["hero"], cues[1]]                                     # e.g. a revoked travel
    again = {c.asset_id: c for c in policy.enforce(restored, assets=_assets("hero", "a"))}
    assert _growing_assets(again) == {"hero"}
