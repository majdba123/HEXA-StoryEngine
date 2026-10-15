"""VP4: hero travel from off-frame and the separate post-settle hero emphasis.

Authorized contract (2026-10-14): one authoritative hero per scene; travel lands on its
unchanged Motion settle; HERO_TRAVEL speed cap; off-screen on every projection; a
separate post-settle scale pulse; the outgoing hero leaves the canvas inside the next
segment. Every rule abstains with an exact reason instead of forcing motion.
"""
from __future__ import annotations

import json

import pytest

from app.choreography import ChoreographyDirective, ChoreographyPlan, SequencePhase
from app.models import (
    CompositionBeat,
    LayoutItem,
    MotionCue,
    MotionSegment,
    StoryBeat,
    VisualAsset,
)
from app.motion.collision import box
from app.motion.hero_travel import EMPHASIS_RANGE, HERO_TRAVEL, SMOOTHSTEP_PEAK, HeroTravelPlanner

_STATIC = {"name": "static_reveal_x", "settle_progress": 1.0, "keyframes": [
    {"progress": 0.0, "dx": 0.0, "dy": 0.0, "scale": 1.0},
    {"progress": 1.0, "dx": 0.0, "dy": 0.0, "scale": 1.0}]}


def _cue(asset: str, start: float, end: float, *, beat: str = "b", segments=(), hold_ms: int = 250) -> MotionCue:
    return MotionCue(beat_id=beat, asset_id=asset, kind="program_v3", start=start, end=end, segments=list(segments),
                     params={"program": json.loads(json.dumps(_STATIC)), "engine_version": 3,
                             "semantic_continuity": {"mode": "ENTER"},
                             "entry_opacity": {"initial": 0.14, "start": start, "settle": end},
                             "semantic_focus": {"rhythm": {"minimum_read_hold_ms": hold_ms}}})


def _beat(beat: str = "b", start: float = 0.0, end: float = 3.0) -> StoryBeat:
    return StoryBeat(id=beat, scene_id=f"s{beat}", start=start, end=end, narration="x", action="REVEAL")


def _assets(*ids: str) -> list[VisualAsset]:
    from pathlib import Path
    return [VisualAsset(id=a, scene_id="s", role="supporting", image_path=Path(f"{a}.png"),
                        extraction_method="test") for a in ids]


def _plan(cues, items, *, beats=None, hero="hero", padding=0.0, text=None, carriers=None):
    beats = beats or [_beat()]
    planner = HeroTravelPlanner(horizontal_padding=padding)
    heroes = hero if isinstance(hero, dict) else {b.id: hero for b in beats}
    directives = tuple(ChoreographyDirective(beat_id=b.id, sequence_id="q", phase=SequencePhase.SETUP,
                                             action="REVEAL", primary_asset_id=heroes[b.id]) for b in beats)
    out = planner.plan(story=beats, composition=[CompositionBeat(beat_id=b.id, items=items) for b in beats],
                       choreography=ChoreographyPlan(directives=directives), motion=cues,
                       assets=_assets(*{c.asset_id for c in cues}), text_boxes=text, referent_carriers=carriers)
    return planner, {(c.beat_id, c.asset_id): c for c in out}


SUPPORT = LayoutItem(asset_id="support", x=0.25, y=0.30, width=0.2, height=0.25)
HERO = LayoutItem(asset_id="hero", x=0.75, y=0.70, width=0.2, height=0.25)


# -- travel --------------------------------------------------------------------------------------
def test_hero_travels_from_off_frame_and_lands_on_its_unchanged_settle() -> None:
    cues = [_cue("support", 0.1, 0.35), _cue("hero", 1.0, 1.3)]
    planner, out = _plan(cues, [SUPPORT, HERO], padding=0.0952)
    hero = out[("b", "hero")]
    decision = next(d for d in planner.decisions if d.asset_id == "hero")
    assert decision.decision == "TRAVEL"
    assert hero.start == pytest.approx(0.1 + 2 / 30)                     # after the earlier reveal
    assert hero.end == 1.3                                               # lands on Motion's settle
    first, last = hero.params["program"]["keyframes"][0], hero.params["program"]["keyframes"][-1]
    start_box = box(HERO, (first["dx"], 0.0, 1.0))
    assert start_box[0] >= 1.0 + 0.0952                                 # off-frame on every projection
    assert (last["dx"], last["dy"], last["scale"]) == (0.0, 0.0, 1.0)    # exact Composition geometry
    assert first["easing"] == "smoothstep"
    speed = SMOOTHSTEP_PEAK * abs(first["dx"]) / (hero.end - hero.start)
    assert speed <= HERO_TRAVEL.max_normalized_speed
    assert "entry_opacity" not in hero.params and hero.params["scene_hero"] is True


def test_scene_opener_never_travels_over_an_empty_canvas() -> None:
    planner, out = _plan([_cue("hero", 0.1, 0.4), _cue("support", 1.0, 1.3)], [SUPPORT, HERO])
    assert next(d for d in planner.decisions).reason == "scene_opener_would_travel_over_empty_canvas"
    assert "hero_travel" not in out[("b", "hero")].params


def test_travel_never_exceeds_the_hero_speed_cap() -> None:
    # Cinematic VNext2 replaced the VP4 cap (1.0 w/s, 0.40 s) with the references' measured
    # slide speed (peak 1.25 w/s, 0.30 s minimum). The cap itself is still never exceeded.
    planner, _ = _plan([_cue("support", 0.9, 1.1), _cue("hero", 1.05, 1.3)], [SUPPORT, HERO])
    reason = next(d for d in planner.decisions).reason
    assert reason.startswith("insufficient_time") or reason.startswith("no_safe_direction:speed")
    planner, out = _plan([_cue("support", 0.9, 1.1), _cue("hero", 1.2, 1.5)], [SUPPORT, HERO])
    decision = next(d for d in planner.decisions)
    assert decision.decision == "TRAVEL"                                  # 1.01 w/s: inside the new cap
    assert decision.peak_speed <= HERO_TRAVEL.max_normalized_speed
    hero = out[("b", "hero")]
    assert hero.end - hero.start >= HERO_TRAVEL.minimum_seconds - 1e-9


def test_a_visible_asset_on_every_path_blocks_travel() -> None:
    wall = LayoutItem(asset_id="support", x=0.5, y=0.70, width=1.0, height=0.25)
    planner, _ = _plan([_cue("support", 0.1, 0.35), _cue("hero", 1.0, 1.3)], [wall, HERO])
    assert next(d for d in planner.decisions).reason.startswith("no_safe_direction")


def test_relation_segment_blocks_travel_but_a_result_pop_is_superseded() -> None:
    relation = MotionSegment(phase="INTERACT", start=1.0, end=1.4, target_asset_id="support",
                             program={"keyframes": [{"progress": 0, "dx": 0.01}, {"progress": 1, "dx": 0}]})
    planner, _ = _plan([_cue("support", 0.1, 0.35), _cue("hero", 1.0, 1.3, segments=[relation])], [SUPPORT, HERO])
    assert next(d for d in planner.decisions).reason == "relation_segment_during_travel"
    pop = MotionSegment(phase="PAYOFF", start=1.0, end=1.3, involvement="RESULT",
                        program={"keyframes": [{"progress": 0, "scale": 1.0}, {"progress": 0.5, "scale": 1.05},
                                               {"progress": 1, "scale": 1.0}]})
    planner, out = _plan([_cue("support", 0.1, 0.35), _cue("hero", 1.0, 1.3, segments=[pop])], [SUPPORT, HERO])
    hero = out[("b", "hero")]
    assert next(d for d in planner.decisions).decision == "TRAVEL"
    assert hero.params["hero_travel"]["superseded"] == "result_arrival_pop"
    assert not any(s.phase == "PAYOFF" and s.start < hero.end for s in hero.segments)


def test_referent_carriers_belong_to_cross_scene_continuity() -> None:
    planner, out = _plan([_cue("support", 0.1, 0.35), _cue("hero", 1.0, 1.3)], [SUPPORT, HERO],
                         carriers={("b", "hero")})
    assert next(d for d in planner.decisions).reason == "locked_family_or_referent_carrier"


def test_travel_crossing_composed_text_returns_to_the_certified_cue() -> None:
    cues = [_cue("support", 0.1, 0.35), _cue("hero", 1.0, 1.3)]
    planner, out = _plan(cues, [SUPPORT, HERO])
    motion = list(out.values())
    revoked = planner.revoke_through_text(motion, cues, {"b": [(0.5, 1.2, (0.9, 0.6, 1.0, 0.8))]})
    hero = next(c for c in revoked if c.asset_id == "hero")
    assert hero.start == 1.0 and "hero_travel" not in hero.params and hero.params["scene_hero"] is True
    assert next(d for d in planner.decisions).reason == "path_crosses_composed_text"


# -- post-settle emphasis ------------------------------------------------------------------------
def test_emphasis_is_a_separate_pulse_after_settle_that_finishes_before_the_hold() -> None:
    planner, out = _plan([_cue("support", 0.1, 0.35), _cue("hero", 1.0, 1.3)], [SUPPORT, HERO])
    hero = out[("b", "hero")]
    pulse = next(s for s in hero.segments if s.semantic_action == "HERO_EMPHASIS")
    assert pulse.start >= hero.end + 1 / 30                              # strictly after arrival
    assert pulse.end <= 3.0 - 0.25 - 2 / 30 + 1e-9                       # read hold kept on the frame grid
    scales = [f["scale"] for f in pulse.program["keyframes"]]
    assert scales[0] == scales[-1] == 1.0
    assert 1 + EMPHASIS_RANGE[0] - 1e-9 <= max(scales) <= 1 + EMPHASIS_RANGE[1] + 1e-9
    entry = next(s for s in hero.segments if s.phase == "ENTRY")         # travel still renders
    assert entry.program["name"] == "hero_travel_entry"


def test_the_same_subject_never_pulses_in_consecutive_scenes() -> None:
    # Cinematic VNext2: references pulse every 2-10 s (n = 25), so a pulse in the next scene
    # is allowed; only the same subject pulsing again reads as repetition.
    beats = [_beat("b1", 0.0, 3.0), _beat("b2", 3.0, 6.0)]
    cues = [_cue("support", 0.1, 0.35, beat="b1"), _cue("hero", 1.0, 1.3, beat="b1"),
            _cue("support", 3.1, 3.35, beat="b2"), _cue("hero", 4.0, 4.3, beat="b2")]
    planner, _ = _plan(cues, [SUPPORT, HERO], beats=beats)
    assert [d.emphasis for d in planner.decisions] == ["applied", "abstain:same_subject_pulsed_in_previous_scene"]
    other = LayoutItem(asset_id="other", x=0.75, y=0.70, width=0.2, height=0.25)
    cues = [_cue("support", 0.1, 0.35, beat="b1"), _cue("hero", 1.0, 1.3, beat="b1"),
            _cue("support", 3.1, 3.35, beat="b2"), _cue("other", 4.0, 4.3, beat="b2")]
    planner, _ = _plan(cues, [SUPPORT, HERO, other], beats=beats, hero={"b1": "hero", "b2": "other"})
    assert [d.emphasis for d in planner.decisions] == ["applied", "applied"]


def test_emphasis_abstains_beside_a_competing_accent_or_without_time() -> None:
    accent = MotionSegment(phase="INTERACT", start=1.4, end=1.9,
                           program={"keyframes": [{"progress": 0, "dx": 0.0}, {"progress": 0.5, "dx": 0.03},
                                                  {"progress": 1, "dx": 0.0}]})
    planner, _ = _plan([_cue("support", 0.1, 0.35, segments=[accent]), _cue("hero", 1.0, 1.3)], [SUPPORT, HERO])
    assert next(d for d in planner.decisions).emphasis == "abstain:competing_accent_from_other_asset"
    planner, _ = _plan([_cue("support", 0.1, 0.35), _cue("hero", 2.4, 2.7)], [SUPPORT, HERO])
    assert next(d for d in planner.decisions).emphasis.startswith("abstain:no_time_after_settle")


def test_programs_never_share_keyframes_so_projection_scales_each_once() -> None:
    """A projected target rescales every program in place; shared keyframes would scale twice."""
    pop = MotionSegment(phase="PAYOFF", start=2.5, end=2.6, involvement="RESULT",
                        program={"keyframes": [{"progress": 0, "scale": 1.0}, {"progress": 1, "scale": 1.0}]})
    for cues in ([_cue("support", 0.1, 0.35), _cue("hero", 1.0, 1.3)],                 # travel + emphasis
                 [_cue("hero", 0.1, 0.4), _cue("support", 1.0, 1.3)],                  # opener: emphasis only
                 [_cue("support", 0.1, 0.35), _cue("hero", 1.0, 1.3, segments=[pop])]):
        _, out = _plan(cues, [SUPPORT, HERO])
        hero = out[("b", "hero")]
        programs = [hero.params.get("program")] + [row.program for row in hero.segments]
        frames = [id(frame) for program in programs if program for frame in program.get("keyframes", [])]
        lists = [id(program.get("keyframes")) for program in programs if program and program.get("keyframes")]
        assert len(frames) == len(set(frames)) and len(lists) == len(set(lists))


def test_a_pulse_revoked_by_composed_text_restores_the_cue_exactly() -> None:
    planner, out = _plan([_cue("support", 0.1, 0.35), _cue("hero", 1.0, 1.3)], [SUPPORT, HERO])
    hero = out[("b", "hero")]
    assert hero.params.get("hero_emphasis") and any(r.program.get("carried_for") for r in hero.segments)
    hugging = (0.851, 0.6, 0.95, 0.7)                     # touches the hero's right edge
    revoked = planner.fit_emphasis_to_text(list(out.values()), {"b": [(0.0, 3.0, hugging)]})
    hero = next(c for c in revoked if c.asset_id == "hero")
    assert "hero_emphasis" not in hero.params and hero.segments == []
    assert next(d for d in planner.decisions if d.asset_id == "hero").emphasis.startswith("revoked:")
