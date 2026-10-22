"""Cinematic VNext2 arrivals: every other entering asset gets one reference gesture from
its own geometry (edge SLIDE, else scale POP, else the certified fade). Story instants
never move; a slide that would cross composed text becomes its pop."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.models import CompositionBeat, LayoutItem, MotionCue, MotionSegment, StoryBeat, VisualAsset
from app.motion.arrivals import OPENER_VISIBLE_SHARE, SLIDE_MAX_PEAK_SPEED, SMOOTHSTEP_PEAK, SecondaryArrivalPlanner
from app.motion.collision import box
from app.motion.resolution import POP_START_SCALE
from app.motion.timing import REFERENCE_SLIDE
from app.render.verification import EncodedMotionVerifier

_STATIC = {"name": "static_reveal_x", "settle_progress": 1.0, "keyframes": [
    {"progress": 0.0, "dx": 0.0, "dy": 0.0, "scale": 1.0},
    {"progress": 1.0, "dx": 0.0, "dy": 0.0, "scale": 1.0}]}


def _cue(asset: str, start: float, end: float, *, segments=(), **params) -> MotionCue:
    return MotionCue(beat_id="b", asset_id=asset, kind="program_v3", start=start, end=end, segments=list(segments),
                     params={"program": json.loads(json.dumps(_STATIC)), "engine_version": 3,
                             "semantic_continuity": {"mode": "ENTER"},
                             "entry_opacity": {"initial": 0.14, "start": start, "settle": end}, **params})


def _assets(*ids: str, parent: dict | None = None) -> list[VisualAsset]:
    return [VisualAsset(id=a, scene_id="s", role="supporting", image_path=Path(f"{a}.png"), extraction_method="test",
                        parent_asset_id=(parent or {}).get(a)) for a in ids]


def _run(cues, items, *, assets=None, sweeps=None):
    planner = SecondaryArrivalPlanner()
    beat = StoryBeat(id="b", scene_id="s", start=0.0, end=3.0, narration="x", action="REVEAL")
    out = planner.plan(story=[beat], composition=[CompositionBeat(beat_id="b", items=items)], motion=cues,
                       assets=assets or _assets(*{c.asset_id for c in cues}), travel_sweeps=sweeps)
    return planner, {c.asset_id: c for c in out}


EDGE = LayoutItem(asset_id="edge", x=0.12, y=0.5, width=0.18, height=0.3)
CENTER = LayoutItem(asset_id="center", x=0.5, y=0.5, width=0.2, height=0.3)


def test_an_asset_near_a_side_edge_slides_in_from_that_edge_at_reference_speed() -> None:
    planner, out = _run([_cue("edge", 1.0, 1.3)], [EDGE])
    cue = out["edge"]
    assert planner.decisions[0].gesture == "SLIDE"
    assert (cue.start, cue.end) == (1.0, 1.3)                           # Story instants unchanged
    frames = cue.params["program"]["keyframes"]
    assert frames[0]["dx"] < 0 and frames[-1]["dx"] == 0.0               # enters from the left edge
    assert cue.params["reference_slide"]["mean_speed"] <= SLIDE_MAX_PEAK_SPEED + 1e-9
    segment = MotionSegment(phase="ENTRY", start=cue.start, end=cue.end, program=cue.params["program"])
    speed = EncodedMotionVerifier._max_normalized_keyframe_speed(segment, duration=cue.end - cue.start,
                                                                item_width=EDGE.width, item_height=EDGE.height)
    assert speed <= REFERENCE_SLIDE.max_normalized_speed
    # Reference profile (docs/reference-motion-grammar.md): the mean speed is what encoded QA measures.
    assert abs(frames[0]["dx"]) / cue.params["reference_slide"]["seconds"] <= SLIDE_MAX_PEAK_SPEED + 1e-6


def _on_frame_share(item: LayoutItem, dx: float) -> float:
    left, right = item.x - item.width / 2 + dx, item.x + item.width / 2 + dx
    return max(0.0, min(1.0, right) - max(0.0, left)) / item.width


def test_a_scene_opener_is_already_partly_on_frame_on_its_reveal_frame() -> None:
    """Level 5 (real Black Hat beat-032, 71.53 s): the scene's first element slid in from
    fully beyond the edge, so the cut landed on a blank frame and the final-media gate
    rejected the export (near-white handoff frame). The opener now starts with
    OPENER_VISIBLE_SHARE of itself on frame; a later element still starts beyond the edge."""
    planner, out = _run([_cue("edge", 1.0, 1.4)], [EDGE])
    opener = out["edge"].params["program"]["keyframes"][0]["dx"]
    assert opener < 0 and _on_frame_share(EDGE, opener) >= OPENER_VISIBLE_SHARE - 1e-6
    earlier = LayoutItem(asset_id="first", x=0.75, y=0.3, width=0.2, height=0.2)
    _, out = _run([_cue("first", 0.4, 0.7), _cue("edge", 1.0, 1.4)], [earlier, EDGE])
    later = out["edge"].params["program"]["keyframes"][0]["dx"]
    assert _on_frame_share(EDGE, later) == 0.0  # not the opener: enters from beyond the edge


def test_a_centred_asset_pops_and_a_tiny_one_keeps_its_fade() -> None:
    # tiny and away from every edge (near the top it would slide in from that edge)
    tiny = LayoutItem(asset_id="tiny", x=0.5, y=0.5, width=0.02, height=0.02)
    planner, out = _run([_cue("center", 1.0, 1.3), _cue("tiny", 1.5, 1.8)], [CENTER, tiny])
    gestures = {d.asset_id: d.gesture for d in planner.decisions}
    assert gestures == {"center": "POP", "tiny": "FADE"}
    assert out["center"].params["program"]["keyframes"][0]["scale"] >= POP_START_SCALE - 1e-9
    assert out["tiny"].params["program"] == _STATIC


def test_a_slide_that_would_cross_a_visible_asset_pops_instead() -> None:
    blocker = LayoutItem(asset_id="blocker", x=0.02, y=0.5, width=0.03, height=0.3)
    planner, _ = _run([_cue("blocker", 0.2, 0.5), _cue("edge", 1.0, 1.3)], [blocker, EDGE])
    assert {d.asset_id: d.gesture for d in planner.decisions}["edge"] == "POP"


def test_a_slide_never_crosses_a_hero_travel_path_in_flight() -> None:
    path = box(EDGE, (0.0, 0.0, 1.0))
    planner, _ = _run([_cue("edge", 1.0, 1.3)], [EDGE], sweeps={("b", "hero"): (0.9, 1.4, path)})
    assert planner.decisions[0].gesture == "POP"


def test_families_children_continuity_and_semantic_accents_keep_their_contracts() -> None:
    accent = MotionSegment(phase="INTERACT", start=1.05, end=1.3, program=_STATIC)
    cues = [_cue("locked", 1.0, 1.3, render_constraints={"geometry_lock": "authored_footprint"}),
            _cue("child", 1.0, 1.3), _cue("carried", 1.0, 1.3, referent_carrier=True),
            _cue("accent", 1.0, 1.3, segments=[accent])]
    items = [LayoutItem(asset_id=a, x=0.5, y=0.5, width=0.2, height=0.3) for a in ("locked", "child", "carried", "accent")]
    planner, out = _run(cues, items, assets=_assets("locked", "child", "carried", "accent", parent={"child": "locked"}))
    assert {d.gesture for d in planner.decisions} == {"FADE"}
    assert all(out[c.asset_id] == c for c in cues)


def test_a_slide_crossing_composed_text_becomes_its_pop() -> None:
    planner, out = _run([_cue("edge", 1.0, 1.3)], [EDGE])
    sweep = planner._slides[("b", "edge")][2]
    text = {"b": [(1.05, 2.0, (sweep[0], sweep[1], sweep[0] + 0.01, sweep[1] + 0.01))]}
    settled = {c.asset_id: c for c in planner.settle_against_text(list(out.values()), text)}
    assert "reference_slide" not in settled["edge"].params
    assert settled["edge"].params["reference_pop"]["profile"] == "REFERENCE_POP"
    assert planner.decisions[0].reason == "slide_path_crosses_composed_text"


def test_a_carried_entry_segment_draws_the_same_gesture() -> None:
    entry = MotionSegment(phase="ENTRY", start=1.0, end=1.3, program={**_STATIC, "qa_base_entry": True})
    pulse = MotionSegment(phase="ESTABLISH", start=1.4, end=1.8, program=_STATIC, semantic_action="HERO_EMPHASIS")
    _, out = _run([_cue("center", 1.0, 1.3, segments=[entry, pulse])], [CENTER])
    row = out["center"].segments[0]
    assert row.program["qa_base_entry"] is True and row.program["keyframes"][0]["scale"] < 1.0
    assert out["center"].segments[1] == pulse


@pytest.mark.parametrize("window", [2 / 30, 0.05, 5 / 30])
def test_windows_below_the_calm_pop_minimum_keep_the_certified_fade(window: float) -> None:
    # A pop squeezed into fewer than 6 frames reads as rushed: the opacity entry stays.
    planner, out = _run([_cue("center", 1.0, 1.0 + window)], [CENTER])
    assert planner.decisions[0].reason == "window_below_pop_minimum"
    assert out["center"].params["program"] == _STATIC


def test_pops_and_slides_are_calm_smoothstep_gestures_without_overshoot() -> None:
    from app.motion.arrivals import SLIDE_MIN_SECONDS
    from app.motion.resolution import POP_MIN_SECONDS, POP_SECONDS

    planner, out = _run([_cue("center", 1.0, 1.0 + POP_MIN_SECONDS), _cue("edge", 2.0, 2.0 + SLIDE_MIN_SECONDS)],
                        [CENTER, EDGE])
    assert {d.asset_id: d.gesture for d in planner.decisions} == {"center": "POP", "edge": "SLIDE"}
    for cue in out.values():
        frames = cue.params["program"]["keyframes"]
        # pops ease in and out; slides enter fast and decelerate (reference grammar G1/G2)
        assert frames[0]["easing"] == ("ease_out_cubic" if cue.asset_id == "edge" else "smoothstep")
        assert max(f["scale"] for f in frames) <= 1.0                     # never grows past rest
    pop = out["center"].params["program"]["keyframes"]
    seconds = out["center"].params["reference_pop"]["seconds"]
    assert POP_MIN_SECONDS - 1e-9 <= seconds <= POP_SECONDS + 1e-9
    assert SMOOTHSTEP_PEAK * (1.0 - pop[0]["scale"]) / seconds <= 1.0 + 1e-9  # peak scale rate per second
    assert out["edge"].params["reference_slide"]["mean_speed"] <= SLIDE_MAX_PEAK_SPEED + 1e-9 <= 0.8 + 1e-9
