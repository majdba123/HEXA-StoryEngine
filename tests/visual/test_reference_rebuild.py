"""Reference rebuild (2026-10-20, full-length review of the approved references).

Each test pins one reference device that was missing or invisible in v8: the scene whip
instead of a cut, deliberate stillness instead of micro nudges/pulses, keyword arrows,
reference-size typography, and visible motion blur. The certified machinery each device
replaces stays tested in its own module (whip off / pulses on there).
"""
from __future__ import annotations

import json

import pytest

import app.boundary.release as release
from app.boundary.release import WHIP_FRAMES, SceneBoundaryPlanner
from app.composition.text_director import REFERENCE_FONT_SCALES, TextPlacementDirector
from app.models import MotionSegment
from app.motion import hero_travel
from app.motion.motion_blur import LEAD_SHUTTER, MAX_LENGTH, MOTION_BLUR_SHUTTER
from app.motion.stillness import ReferenceStillnessPolicy, is_out_and_back, is_reference_still
from app.render.connection import (
    LABEL_MIN_LENGTH_PX,
    LabelAnchor,
    label_arrow_specs,
)
from app.render.verification import EncodedMotionVerifier
from tests.visual.test_sprint_4_5_scene_handoffs import FPS, NEW_ON_OLD, Scene, _cue

_NUDGE = {"name": "reference_directional_handoff", "keyframes": [
    {"progress": 0.0, "dx": 0.0, "dy": 0.0, "scale": 1.0},
    {"progress": 0.4, "dx": 0.006, "dy": -0.009, "scale": 1.012},
    {"progress": 1.0, "dx": 0.0, "dy": 0.0, "scale": 1.0}]}


# -- scene whip (G16) ---------------------------------------------------------------
def test_a_cut_becomes_one_whip_of_the_whole_old_scene_at_the_unchanged_opener() -> None:
    scene = Scene(lead=3, opener=NEW_ON_OLD)
    row = scene.plan()
    assert row.audit["hero_exit"] == "scene_whip"
    assert set(row.overlap_exits) == {"old_a", "old_b"}            # the whole scene, one block
    specs = list(row.overlap_exits.values())
    assert all(spec == specs[0] for spec in specs)                 # one rigid path and clock
    opener = scene.boundary + 3 / FPS
    assert specs[0]["start"] == pytest.approx(opener)              # Story's opener unchanged
    assert specs[0]["end"] - specs[0]["start"] == pytest.approx(WHIP_FRAMES / FPS)
    assert row.exit_motion_blur["owner"] == "BOUNDARY"             # smeared like the reference


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


# -- keyword arrows (G17) -----------------------------------------------------------
def _label(box, start=1.0, end=3.0, asset="lock"):
    return LabelAnchor(asset_id=asset, box=box, start=start, end=end)


def test_a_keyword_gets_one_curved_arrow_to_what_it_names_for_as_long_as_it_is_shown() -> None:
    specs = label_arrow_specs(
        labels=[_label((1200.0, 100.0, 1500.0, 200.0))],
        visible={"lock": (600.0, 400.0, 900.0, 800.0)}, revealed={"lock": 0.5}, family={},
        segment_start=0.0, duration=4.0, frame=(1920, 1080))
    assert len(specs) == 1
    spec = specs[0]
    assert (spec.start, spec.end) == (1.0, 3.0)              # with the word, gone with it
    assert spec.control is not None                          # curved, like the references
    def near(point, box, margin=16.0):
        return box[0] - margin <= point[0] <= box[2] + margin and box[1] - margin <= point[1] <= box[3] + margin

    assert near(spec.p0, (1200.0, 100.0, 1500.0, 200.0))     # starts at the word ...
    assert near(spec.p1, (600.0, 400.0, 900.0, 800.0))       # ... and ends at the lock


def test_no_arrow_when_the_word_touches_its_artwork_or_the_path_is_blocked_or_too_short() -> None:
    lock = (600.0, 400.0, 900.0, 800.0)
    touching = _label((880.0, 300.0, 1100.0, 420.0))
    near = _label((920.0, 380.0, 920.0 + 200.0, 440.0))      # gap below the minimum arrow
    far = _label((1300.0, 100.0, 1600.0, 200.0))
    wall = (950.0, 0.0, 1250.0, 1080.0)                       # another asset across every route
    for labels, visible in (([touching], {"lock": lock}), ([near], {"lock": lock}),
                            ([far], {"lock": lock, "wall": wall})):
        assert label_arrow_specs(labels=labels, visible=visible, revealed={"lock": 0.5, "wall": 0.0},
                                 family={}, segment_start=0.0, duration=4.0, frame=(1920, 1080)) == []
    assert LABEL_MIN_LENGTH_PX >= 80.0


def test_an_arrow_never_points_at_artwork_before_it_is_revealed() -> None:
    specs = label_arrow_specs(
        labels=[_label((1200.0, 100.0, 1500.0, 200.0), start=1.0, end=3.0)],
        visible={"lock": (600.0, 400.0, 900.0, 800.0)}, revealed={"lock": 2.0}, family={},
        segment_start=0.0, duration=4.0, frame=(1920, 1080))
    assert specs and specs[0].start == 2.0


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
