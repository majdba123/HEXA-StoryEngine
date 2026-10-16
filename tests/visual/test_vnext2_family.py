"""Cinematic VNext2: a Pass2 family whose layers share one box and one clock moves as one
rigid unit (pop, slide, travel); its locked layers follow the primary's transform."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.choreography import ChoreographyDirective, ChoreographyPlan, SequencePhase
from app.models import CompositionBeat, LayoutItem, MotionCue, StoryBeat, VisualAsset
from app.motion.arrivals import SecondaryArrivalPlanner
from app.motion.family import FOLLOW_PARAM, bind_families, follow, rigid_followers
from app.motion.hero_travel import HeroTravelPlanner

_STATIC = {"name": "static_reveal_x", "settle_progress": 1.0, "keyframes": [
    {"progress": 0.0, "dx": 0.0, "dy": 0.0, "scale": 1.0},
    {"progress": 1.0, "dx": 0.0, "dy": 0.0, "scale": 1.0}]}
LOCK = {"geometry_lock": "authored_footprint", "reveal_mode": "alpha_only"}


def _cue(asset: str, start: float, end: float, **params) -> MotionCue:
    return MotionCue(beat_id="b", asset_id=asset, kind="program_v3", start=start, end=end,
                     params={"program": json.loads(json.dumps(_STATIC)), "engine_version": 3,
                             "semantic_continuity": {"mode": "ENTER"},
                             "entry_opacity": {"initial": 0.14, "start": start, "settle": end},
                             "semantic_focus": {"rhythm": {"minimum_read_hold_ms": 250}}, **params})


def _assets(*ids: str) -> list[VisualAsset]:
    return [VisualAsset(id=a, scene_id="s", role="supporting", image_path=Path(f"{a}.png"), extraction_method="test",
                        parent_asset_id=a.split(":secondary-")[0] if ":secondary-" in a else None,
                        asset_family_id=a.split(":secondary-")[0]) for a in ids]


def _item(asset: str, x: float = 0.5, y: float = 0.5, w: float = 0.2, h: float = 0.3) -> LayoutItem:
    return LayoutItem(asset_id=asset, x=x, y=y, width=w, height=h)


FAMILY = [_cue("f", 1.0, 1.3), _cue("f:secondary-01", 1.0, 1.3, render_constraints=LOCK)]


def test_rigid_followers_requires_one_box_and_one_clock() -> None:
    layout = {"f": _item("f"), "f:secondary-01": _item("f:secondary-01")}
    assets = {a.id: a for a in _assets("f", "f:secondary-01")}
    assert [c.asset_id for c in rigid_followers(FAMILY[0], FAMILY, layout, assets)] == ["f:secondary-01"]
    assert rigid_followers(FAMILY[1], FAMILY, layout, assets) is None             # only the primary leads
    moved = {**layout, "f:secondary-01": _item("f:secondary-01", x=0.52)}
    assert rigid_followers(FAMILY[0], FAMILY, moved, assets) is None               # split boxes never move
    late = [FAMILY[0], _cue("f:secondary-01", 1.1, 1.3, render_constraints=LOCK)]
    assert rigid_followers(late[0], late, layout, assets) is None                  # split clocks never move
    assert rigid_followers(_cue("solo", 1.0, 1.3), [_cue("solo", 1.0, 1.3)], {}, {}) == []


def test_a_rigid_family_pops_as_one_unit_on_one_clock() -> None:
    planner = SecondaryArrivalPlanner()
    beat = StoryBeat(id="b", scene_id="s", start=0.0, end=3.0, narration="x", action="REVEAL")
    items = [_item("f"), _item("f:secondary-01")]
    out = {c.asset_id: c for c in planner.plan(story=[beat], composition=[CompositionBeat(beat_id="b", items=items)],
                                               motion=list(FAMILY), assets=_assets("f", "f:secondary-01"))}
    lead, layer = out["f"], out["f:secondary-01"]
    assert lead.params["reference_pop"] and layer.params[FOLLOW_PARAM] == "f"
    assert layer.params["entry_opacity"] == lead.params["entry_opacity"]           # one family clock
    assert (layer.start, layer.end) == (lead.start, lead.end) == (1.0, 1.3)        # Story instants kept
    assert layer.params["program"] == _STATIC                                       # the layer itself stays locked
    gestures = {d.asset_id: d.gesture for d in planner.decisions}
    assert gestures == {"f": "POP", "f:secondary-01": "FOLLOW"}


def test_a_rigid_family_hero_travels_as_one_unit() -> None:
    beat = StoryBeat(id="b", scene_id="s", start=0.0, end=3.0, narration="x", action="REVEAL")
    support = _cue("support", 0.1, 0.35)
    cues = [support, _cue("f", 1.0, 1.3), _cue("f:secondary-01", 1.0, 1.3, render_constraints=LOCK)]
    items = [_item("support", x=0.25, y=0.3), _item("f", x=0.75, y=0.7, w=0.2, h=0.25),
             _item("f:secondary-01", x=0.75, y=0.7, w=0.2, h=0.25)]
    planner = HeroTravelPlanner()
    directive = ChoreographyDirective(beat_id="b", sequence_id="q", phase=SequencePhase.SETUP, action="REVEAL",
                                      primary_asset_id="f")
    out = {c.asset_id: c for c in planner.plan(
        story=[beat], composition=[CompositionBeat(beat_id="b", items=items)],
        choreography=ChoreographyPlan(directives=(directive,)), motion=cues,
        assets=_assets("support", "f", "f:secondary-01"))}
    lead, layer = out["f"], out["f:secondary-01"]
    assert next(d for d in planner.decisions).decision == "TRAVEL"
    assert layer.params[FOLLOW_PARAM] == "f" and layer.start == lead.start < 1.0   # enters with its primary
    assert "entry_opacity" not in layer.params and "entry_opacity" not in lead.params
    restored = planner.revoke_through_text(list(out.values()), cues, {"b": [(0.0, 3.0, (0.0, 0.0, 1.0, 1.0))]})
    assert {c.asset_id: c for c in restored}["f:secondary-01"] == cues[2]          # the unit returns together


def test_bind_marks_only_locked_layers_that_share_their_primary_box() -> None:
    layouts = {"b": {"f": _item("f"), "f:secondary-01": _item("f:secondary-01"),
                     "g": _item("g"), "g:secondary-01": _item("g:secondary-01", x=0.3)}}
    cues = [*FAMILY, _cue("g", 1.0, 1.3), _cue("g:secondary-01", 1.0, 1.3, render_constraints=LOCK)]
    out = {c.asset_id: c for c in bind_families(cues, layouts, {a.id: a for a in _assets(
        "f", "f:secondary-01", "g", "g:secondary-01")})}
    assert out["f:secondary-01"].params[FOLLOW_PARAM] == "f"
    assert FOLLOW_PARAM not in out["g:secondary-01"].params                          # different box: stays locked
    assert FOLLOW_PARAM not in out["f"].params


def test_follow_copies_the_leader_clock_without_touching_the_layer_program() -> None:
    lead = FAMILY[0].model_copy(update={"start": 0.8, "params": {**FAMILY[0].params, "entry_opacity": None}})
    layer = follow(FAMILY[1], lead)
    assert layer.start == pytest.approx(0.8) and "entry_opacity" not in layer.params
    assert layer.params["program"] == FAMILY[1].params["program"]
