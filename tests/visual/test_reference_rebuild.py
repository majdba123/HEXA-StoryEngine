"""Reference rebuild (2026-10-20, full-length review of the approved references; R2 after user review).

Each test pins one reference device that was missing or invisible in v8: the scene whip
instead of a cut, deliberate stillness instead of micro nudges/pulses, keyword arrows,
reference-size typography, and visible motion blur. The certified machinery each device
replaces stays tested in its own module (whip off / pulses on there).
"""
from __future__ import annotations

import json

import pytest

import app.boundary.release as release
from app.boundary.release import FADE_FRAMES, WHIP_FRAMES, SceneBoundaryPlanner
from app.composition.text_director import REFERENCE_FONT_SCALES, TextPlacementDirector
from app.models import AssetActivation, MotionSegment, StoryEntity, StorySemanticContext
from app.motion import hero_travel
from app.motion.motion_blur import LEAD_SHUTTER, MAX_LENGTH, MOTION_BLUR_SHUTTER
from app.motion.stillness import ReferenceStillnessPolicy, is_out_and_back, is_reference_still
from app.motion.landing import ReferenceLandingPolicy
from app.motion.spoken_pulse import SpokenPulsePolicy
from app.render.connection import (
    LABEL_MAX_LENGTH,
    LABEL_MIN_LENGTH_PX,
    LABEL_SETTLE_PAUSE,
    LabelAnchor,
    label_arrow_specs,
)
from app.render.verification import EncodedMotionVerifier
from tests.visual.test_sprint_4_5_scene_handoffs import FPS, NEW_ON_OLD, Scene, _cue

_NUDGE = {"name": "reference_directional_handoff", "keyframes": [
    {"progress": 0.0, "dx": 0.0, "dy": 0.0, "scale": 1.0},
    {"progress": 0.4, "dx": 0.006, "dy": -0.009, "scale": 1.012},
    {"progress": 1.0, "dx": 0.0, "dy": 0.0, "scale": 1.0}]}


# -- scene change: fade to white, whip only for a character swap (G9 / G16) ----------
def _with_roles(scene: Scene, roles: dict[str, str]) -> Scene:
    for position, beat in enumerate(scene.story):
        ids = {item.asset_id for item in scene.composition[position].items}
        entities = [StoryEntity(unit_id=f"u_{a}", role=r) for a, r in roles.items() if a in ids]
        scene.story[position] = beat.model_copy(update={
            "semantic_context": StorySemanticContext(entities=entities),
            "asset_activations": [AssetActivation(asset_id=a, semantic_unit_id=f"u_{a}") for a in ids],
        })
    return scene


def test_a_cut_becomes_a_fade_of_the_whole_old_scene_at_the_unchanged_opener() -> None:
    scene = Scene(lead=3, opener=NEW_ON_OLD)
    row = scene.plan()
    assert row.audit["hero_exit"] == "scene_fade"
    assert set(row.overlap_exits) == {"old_a", "old_b"}            # the whole scene, one block
    specs = list(row.overlap_exits.values())
    assert all(spec == specs[0] for spec in specs)                 # one clock
    opener = scene.boundary + 3 / FPS
    assert specs[0]["start"] == pytest.approx(opener)              # Story's opener unchanged
    assert specs[0]["end"] - specs[0]["start"] == pytest.approx(FADE_FRAMES / FPS, abs=1e-5)
    assert specs[0]["fade"] == 1.0 and row.exit_motion_blur == {}  # clears in place, no smear


def test_a_character_swap_is_carried_by_a_blurred_whip() -> None:
    scene = _with_roles(Scene(lead=3, opener=NEW_ON_OLD), {"old_a": "CHARACTER", "new_a": "CHARACTER"})
    row = scene.plan()
    assert row.audit["hero_exit"] == "scene_whip"
    spec = next(iter(row.overlap_exits.values()))
    assert spec["fade"] == 0.0 and spec["end"] - spec["start"] == pytest.approx(WHIP_FRAMES / FPS, abs=1e-5)
    assert row.exit_motion_blur["owner"] == "BOUNDARY"
    # an object opening the next scene is no character swap: the old scene fades
    objects = _with_roles(Scene(lead=3, opener=NEW_ON_OLD), {"old_a": "CHARACTER", "new_a": "OBJECT"})
    assert objects.plan().audit["hero_exit"] == "scene_fade"


def test_continuing_artwork_keeps_its_certified_boundary_instead_of_a_whip() -> None:
    scene = Scene(lead=3, opener=NEW_ON_OLD)
    scene.motion[0] = scene.motion[0].model_copy(update={"params": {**scene.motion[0].params,
                                                                    "referent_carrier": True}})
    assert scene.plan().audit.get("hero_exit") != "scene_whip"


def test_whip_switch_off_restores_the_certified_boundary(monkeypatch) -> None:
    monkeypatch.setattr(release, "SCENE_WHIP", False)
    assert Scene(lead=3, opener=NEW_ON_OLD).plan(SceneBoundaryPlanner()).overlap_exits == {}


# -- stillness (G18) ----------------------------------------------------------------
def test_in_place_micro_gestures_become_still_and_arrivals_are_untouched() -> None:
    arrival = {"name": "reference_slide_entry", "keyframes": [
        {"progress": 0.0, "dx": -0.2, "dy": 0.0, "scale": 1.0},
        {"progress": 1.0, "dx": 0.0, "dy": 0.0, "scale": 1.0}]}
    cue = _cue("b2", "new_a", 2.1, 0.4, segments=[
        MotionSegment(phase="ENTRY", start=2.1, end=2.4, program=arrival),
        MotionSegment(phase="INTERACT", start=2.2, end=2.5, program=json.loads(json.dumps(_NUDGE)),
                      relationship="ENABLES", source_asset_id="new_a", target_asset_id="new_b")])
    out = ReferenceStillnessPolicy().apply([cue])[0]
    entry, accent = out.segments
    assert entry.program == arrival
    assert is_reference_still(accent.program) and not is_out_and_back(accent.program)
    assert (accent.start, accent.end, accent.relationship) == (2.2, 2.5, "ENABLES")


def test_qa_accepts_deliberate_stillness_but_still_rejects_a_weak_gesture() -> None:
    def plan_with(program):
        scene = Scene(lead=10)
        scene.motion[-2] = _cue("b2", "new_a", scene.boundary + 10 / FPS, 0.6, segments=[
            MotionSegment(phase="INTERACT", start=scene.boundary + 0.4, end=scene.boundary + 0.7,
                          program=program)])
        return scene.render_plan([])

    still = ReferenceStillnessPolicy().apply(plan_with(_NUDGE).motion)
    plan = plan_with(_NUDGE).model_copy(update={"motion": still})
    assert EncodedMotionVerifier().preflight(plan).ok
    weak = {**_NUDGE, "keyframes": [{**row, "dx": row["dx"] * 0.02, "dy": row["dy"] * 0.02,
                                     "scale": 1.0 + (row["scale"] - 1.0) * 0.02}
                                    for row in _NUDGE["keyframes"]]}
    codes = {row.code for row in EncodedMotionVerifier().preflight(plan_with(weak)).violations}
    assert "MOTION_BELOW_PERCEPTUAL_FLOOR" in codes


def test_production_never_pulses_a_subject_at_rest() -> None:
    assert hero_travel.POST_SETTLE_PULSES is False


# -- keyword arrows (G17): short, beside the word, never through any drawing ----------
def _label(box, start=1.0, end=3.0, asset="lock"):
    return LabelAnchor(asset_id=asset, box=box, start=start, end=end)


def _disc(path, size=300):
    """An asset whose visible drawing is a disc well inside its transparent canvas."""
    import numpy as np
    from PIL import Image

    yy, xx = np.mgrid[0:size, 0:size]
    art = np.zeros((size, size, 4), np.uint8)
    art[(xx - size / 2) ** 2 + (yy - size / 2) ** 2 <= (size * 0.3) ** 2] = (200, 40, 40, 255)
    Image.fromarray(art).save(path)
    return path


LOCK_BOX = (800.0, 300.0, 1100.0, 600.0)   # Composition box; the disc is radius 90 at (950, 450)


def _arrows(labels, *, visible=None, settled=None, images=None, boxes=None):
    return label_arrow_specs(labels=labels, visible=visible or {"lock": (860.0, 360.0, 1040.0, 540.0)},
                             settled=settled or {"lock": 0.5}, segment_start=0.0, duration=4.0,
                             frame=(1920, 1080), images=images, boxes=boxes)


def test_the_arrow_head_stops_just_outside_the_drawing_not_inside_its_box(tmp_path) -> None:
    specs = _arrows([_label((1180.0, 410.0, 1380.0, 490.0))],
                    images={"lock": _disc(tmp_path / "lock.png")}, boxes={"lock": LOCK_BOX})
    assert len(specs) == 1
    tip = specs[0].p1
    distance = ((tip[0] - 950.0) ** 2 + (tip[1] - 450.0) ** 2) ** 0.5
    assert 90.0 <= distance <= 90.0 + 30.0          # outside the disc, close to its edge
    length = ((tip[0] - specs[0].p0[0]) ** 2 + (tip[1] - specs[0].p0[1]) ** 2) ** 0.5
    assert LABEL_MIN_LENGTH_PX <= length <= LABEL_MAX_LENGTH * 1920   # short, like the references


def test_no_long_arrow_and_no_arrow_through_another_drawing_even_of_the_same_family() -> None:
    far = _label((1500.0, 80.0, 1800.0, 160.0))       # would cross the frame: no arrow
    assert _arrows([far]) == []
    beside = _label((1180.0, 410.0, 1380.0, 490.0))
    piece = (1070.0, 380.0, 1150.0, 520.0)            # e.g. the lock's own dots, in the gap
    assert _arrows([beside], visible={"lock": (860.0, 360.0, 1040.0, 540.0), "lock:dots": piece}) == []
    touching = _label((1030.0, 300.0, 1250.0, 380.0))
    assert _arrows([touching]) == []


def test_the_arrow_waits_for_its_element_to_settle_and_for_the_word_to_be_read() -> None:
    word = _label((1180.0, 410.0, 1380.0, 490.0), start=1.0, end=3.0)
    assert _arrows([word], settled={"lock": 2.0})[0].start == 2.0
    assert _arrows([word], settled={"lock": 0.2})[0].start == pytest.approx(1.0 + LABEL_SETTLE_PAUSE)
    assert _arrows([word], settled={"lock": 2.0})[0].end == 3.0       # gone with the word


# -- high-scale landing (G19) ---------------------------------------------------------
def _landing_beat(roles):
    from app.models import StoryBeat

    entities = [StoryEntity(unit_id=f"u_{a}", role=r) for a, r in roles.items()]
    return StoryBeat(id="b2", scene_id="s2", start=2.0, end=5.0, narration="x", action="REVEAL",
                     semantic_context=StorySemanticContext(entities=entities),
                     asset_activations=[AssetActivation(asset_id=a, semantic_unit_id=f"u_{a}") for a in roles])


def test_a_named_object_lands_in_place_from_a_high_scale_and_a_character_keeps_its_entrance() -> None:
    from app.models import CompositionBeat, LayoutItem, VisualAsset

    beat = _landing_beat({"obj": "OBJECT", "hero": "CHARACTER"})
    items = [LayoutItem(asset_id="obj", x=0.3, y=0.5, width=0.2, height=0.3),
             LayoutItem(asset_id="hero", x=0.75, y=0.5, width=0.25, height=0.6)]
    slide = {"name": "reference_slide_arrival", "settle_progress": 1.0, "keyframes": [
        {"progress": 0.0, "dx": -0.2, "dy": 0.0, "scale": 1.0}, {"progress": 1.0, "dx": 0.0, "dy": 0.0, "scale": 1.0}]}
    cues = [_cue("b2", "obj", 2.5, 0.4).model_copy(update={"params": {
                **_cue("b2", "obj", 2.5, 0.4).params, "program": slide, "reference_slide": {"dx": -0.2}}}),
            _cue("b2", "hero", 2.5, 0.4).model_copy(update={"params": {
                **_cue("b2", "hero", 2.5, 0.4).params, "program": slide}})]
    assets = [VisualAsset(id=a, scene_id="s2", role="supporting", image_path=f"{a}.png", extraction_method="t")
              for a in ("obj", "hero")]
    policy = ReferenceLandingPolicy()
    out = {c.asset_id: c for c in policy.apply(story=[beat], composition=[CompositionBeat(beat_id="b2", items=items)],
                                               motion=cues, assets=assets)}
    landed = out["obj"]
    frames = landed.params["program"]["keyframes"]
    assert frames[0]["scale"] > 1.1 and frames[-1]["scale"] == 1.0          # big -> authored size
    assert all(f["dx"] == 0.0 and f["dy"] == 0.0 for f in frames)          # in place, no slide
    assert "reference_slide" not in landed.params
    assert landed.params["reference_landing"]["defocus_px"] > 0            # soft -> sharp
    assert (landed.start, landed.end) == (2.5, 2.9)                        # Story instants kept
    assert out["hero"].params["program"] == slide                          # characters keep theirs


# -- the element being spoken about pulses on its word ----------------------------------
def test_an_element_already_on_screen_pulses_exactly_when_it_is_spoken() -> None:
    from app.models import CompositionBeat, LayoutItem, TextCue, TextPlan, VisualAsset

    beat = _landing_beat({"obj": "OBJECT"})
    item = LayoutItem(asset_id="obj", x=0.3, y=0.5, width=0.2, height=0.3)
    cue = _cue("b2", "obj", 2.2, 0.3)
    word = TextCue(id="t", beat_id="b2", text="x", semantic_type="emphasis", source_char_start=0,
                   source_char_end=1, spoken_start=3.4, spoken_end=3.8, emphasis_time=3.4,
                   style_id="emphasis", anchor_asset_id="obj")
    asset = VisualAsset(id="obj", scene_id="s2", role="supporting", image_path="obj.png", extraction_method="t")
    out = SpokenPulsePolicy().apply(story=[beat], composition=[CompositionBeat(beat_id="b2", items=[item])],
                                    motion=[cue], assets=[asset], text=TextPlan(cues=[word]))[0]
    pulse = [row for row in out.segments if row.program.get("name") == "reference_spoken_pulse"]
    assert len(pulse) == 1 and pulse[0].start == pytest.approx(3.4)        # on the spoken word
    peak = max(f["scale"] for f in pulse[0].program["keyframes"])
    assert 1.05 <= peak <= 1.15 and pulse[0].program["keyframes"][-1]["scale"] == 1.0
    # an element still arriving when it is named gets no extra pulse (its arrival is the pulse)
    early = word.model_copy(update={"spoken_start": 2.3})
    again = SpokenPulsePolicy().apply(story=[beat], composition=[CompositionBeat(beat_id="b2", items=[item])],
                                      motion=[cue], assets=[asset], text=TextPlan(cues=[early]))[0]
    assert not any(row.program.get("name") == "reference_spoken_pulse" for row in again.segments)


# -- typography and blur (G14 / G15) ------------------------------------------------
def test_reference_typography_rungs_come_first_and_never_exceed_the_safe_width() -> None:
    from app.models import TextCue

    cue = TextCue(id="t", beat_id="b", text="كلمة مرور ضعيفة جدا جدا جدا", semantic_type="emphasis",
                  source_char_start=0, source_char_end=5, spoken_start=0.0, spoken_end=1.0,
                  emphasis_time=0.0, style_id="emphasis", priority=90)
    assert TextPlacementDirector._font_scales(cue)[:len(REFERENCE_FONT_SCALES)] == REFERENCE_FONT_SCALES
    assert not TextPlacementDirector._fits_safe_width(cue, max(REFERENCE_FONT_SCALES))


def test_motion_blur_matches_the_reference_exposure() -> None:
    assert MOTION_BLUR_SHUTTER == 1.0 and LEAD_SHUTTER > MOTION_BLUR_SHUTTER
    assert MAX_LENGTH >= 0.2   # whips smear about an element's own size


# -- elements interact when their relation is spoken -----------------------------------
def _relation_beat(order: str):
    from app.models import StoryBeat, StoryRelation

    entities = [StoryEntity(unit_id="u_cause", role="OBJECT"), StoryEntity(unit_id="u_effect", role="RESULT")]
    relation = StoryRelation(source_unit_id="u_cause", target_unit_id="u_effect", kind="ENABLES",
                             authority="FINAL_PACKAGE_ASSET_RELATION", spoken_start=2.2, causal=True)
    beat = StoryBeat(id="b2", scene_id="s2", start=2.0, end=5.0, narration="x", action="REVEAL",
                     semantic_context=StorySemanticContext(entities=entities, relations=[relation]),
                     asset_activations=[AssetActivation(asset_id=a, semantic_unit_id=f"u_{a}")
                                        for a in ("cause", "effect")])
    first, second = (2.2, 3.0) if order == "cause_first" else (3.0, 2.2)
    return beat, {"cause": _cue("b2", "cause", first, 0.25), "effect": _cue("b2", "effect", second, 0.25)}


def test_cause_first_draws_the_arrow_before_the_effect_lands_at_its_tip() -> None:
    from app.motion.interaction import ARROW_SECONDS, interaction_schedule

    beat, cues = _relation_beat("cause_first")
    (row,) = interaction_schedule(beat, cues)
    assert (row.source, row.target, row.kind) == ("cause", "effect", "ENABLES")
    assert row.arrow_start == pytest.approx(3.0 - ARROW_SECONDS)   # head reaches the effect as it lands
    assert row.source_pulse == row.arrow_start and row.target_pulse is None


def test_effect_first_draws_the_arrow_after_both_settle_and_the_effect_answers() -> None:
    from app.motion.interaction import ARROW_SECONDS, interaction_schedule

    beat, cues = _relation_beat("effect_first")
    (row,) = interaction_schedule(beat, cues)
    assert row.arrow_start >= 3.25                                  # both ends have settled
    assert row.target_pulse == pytest.approx(row.arrow_start + ARROW_SECONDS)


def test_relation_arrow_runs_silhouette_to_silhouette_and_never_through_a_third_drawing(tmp_path) -> None:
    from app.render.connection import RELATION_MAX_LENGTH, relation_arrow_specs

    disc = _disc(tmp_path / "d.png")
    boxes = {"cause": (300.0, 300.0, 600.0, 600.0), "effect": (800.0, 300.0, 1100.0, 600.0)}
    visible = {"cause": (360.0, 360.0, 540.0, 540.0), "effect": (860.0, 360.0, 1040.0, 540.0)}
    kwargs = dict(interactions=[("cause", "effect", 2.5)], images={"cause": disc, "effect": disc}, boxes=boxes,
                  obstacles=[], segment_start=2.0, duration=3.0, frame=(1920, 1080))
    (spec,) = relation_arrow_specs(visible=visible, **kwargs)
    assert spec.start == pytest.approx(0.5) and spec.end == 3.0       # held until the scene changes
    assert 540.0 <= spec.p0[0] <= 570.0 and 830.0 <= spec.p1[0] <= 860.0   # edge to edge, outside both
    assert ((spec.p1[0] - spec.p0[0]) ** 2) ** 0.5 <= RELATION_MAX_LENGTH * 1920
    blocked = {**visible, "wall": (640.0, 0.0, 760.0, 1080.0)}
    assert relation_arrow_specs(visible=blocked, **kwargs) == []
