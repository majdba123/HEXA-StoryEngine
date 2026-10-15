"""VNext: an entry arrives at entry speed; Story windows and peaks are unchanged."""
from __future__ import annotations

import pytest

from app.models import CompositionBeat, LayoutItem, MotionCue, MotionSegment
from app.motion.arrival import REFERENCE_MAX_OPACITY_RAMP, EntryArrivalPolicy, bounded_entry
from app.motion.timing import motion_comfort
from app.render.verification import EncodedMotionVerifier
from app.shared.handoff import LayerHandoffValidator

ITEM = LayoutItem(asset_id="a", x=0.3, y=0.5, width=0.25, height=0.4)
LAYOUT = [CompositionBeat(beat_id="b", items=[ITEM])]
ARRIVAL = [{"progress": 0.0, "dx": -0.03, "dy": 0.0, "scale": 0.96},
           {"progress": 0.48, "dx": -0.012, "dy": 0.0, "scale": 0.985},
           {"progress": 0.78, "dx": 0.0, "dy": 0.0, "scale": 1.0},
           {"progress": 1.0, "dx": 0.0, "dy": 0.0, "scale": 1.0}]
PEAK = [{"progress": 0.0, "dx": 0.0, "dy": 0.0, "scale": 0.988},
        {"progress": 0.964, "dx": 0.005, "dy": 0.0, "scale": 1.014},
        {"progress": 1.0, "dx": 0.0, "dy": 0.0, "scale": 1.0}]


def _speed(frames: list[dict], duration: float) -> float:
    segment = MotionSegment(phase="ENTRY", start=0.0, end=duration, program={"keyframes": frames})
    return EncodedMotionVerifier._max_normalized_keyframe_speed(
        segment, duration=duration, item_width=ITEM.width, item_height=ITEM.height)


def test_a_long_arrival_finishes_within_the_entry_comfort_target_and_then_rests() -> None:
    frames, audit = bounded_entry(ARRIVAL, 1.6, ITEM)
    arrival = next(row["progress"] for row in frames if row["scale"] == 1.0) * 1.6
    assert audit["shape"] == "ARRIVAL" and audit["approach_from"] == pytest.approx(0.78 * 1.6, abs=1e-3)
    assert arrival == pytest.approx(13 / 30, abs=1e-6)                         # 13 frames, not 1.25 s
    assert frames[0] == ARRIVAL[0] and frames[-1]["progress"] == 1.0
    assert _speed(frames, 1.6) <= motion_comfort("ENTRY").max_normalized_speed + 1e-9


def test_a_long_approach_to_a_spoken_accent_becomes_entry_hold_then_accent() -> None:
    frames, audit = bounded_entry(PEAK, 2.0, ITEM)
    assert audit["shape"] == "PEAK"
    progress = [row["progress"] for row in frames]
    assert progress == sorted(progress)
    assert frames[1]["scale"] == 1.0 and frames[1]["progress"] * 2.0 == pytest.approx(13 / 30)
    assert frames[2]["scale"] == 1.0                                            # still until the word
    assert frames[3] == PEAK[1]                                                  # accent unchanged, same instant
    assert frames[-1] == PEAK[-1]
    rise = (frames[3]["progress"] - frames[2]["progress"]) * 2.0
    assert rise == pytest.approx((1.0 - 0.964) * 2.0)                            # rises as fast as it falls


def test_short_entries_and_static_programs_are_untouched() -> None:
    assert bounded_entry(ARRIVAL, 0.5, ITEM) is None                             # approach 0.39 s
    static = [{"progress": 0.0, "dx": 0.0, "dy": 0.0, "scale": 1.0},
              {"progress": 1.0, "dx": 0.0, "dy": 0.0, "scale": 1.0}]
    assert bounded_entry(static, 2.0, ITEM) is None


def _cue(**params) -> MotionCue:
    return MotionCue(beat_id="b", asset_id="a", kind="program_v3", start=10.0, end=11.6,
                     params={"program": {"name": "reference_slide_settle", "keyframes": ARRIVAL}, **params})


def test_policy_keeps_the_story_window_and_ends_a_long_opacity_ramp_with_the_arrival() -> None:
    cue = _cue(entry_opacity={"initial": 0.14, "start": 10.0, "settle": 11.6})
    out = EntryArrivalPolicy().apply([cue], composition=LAYOUT)[0]
    assert (out.start, out.end) == (cue.start, cue.end)
    ramp = out.params["entry_opacity"]
    assert ramp["start"] == 10.0 and ramp["settle"] == pytest.approx(10.0 + REFERENCE_MAX_OPACITY_RAMP)
    assert LayerHandoffValidator._entry_opacity_inside_story_window(ramp, out)
    assert out.params["entry_arrival"]["target"] == "base_program"


def test_hero_travel_and_locked_families_are_never_retimed() -> None:
    travel = _cue(hero_travel={"mode": "offscreen"})
    locked = _cue(render_constraints={"geometry_lock": "authored_footprint"})
    for cue in (travel, locked):
        assert EntryArrivalPolicy().apply([cue], composition=LAYOUT)[0] is cue


def test_an_opacity_clock_may_finish_early_but_never_after_the_story_settle() -> None:
    cue = _cue()
    assert LayerHandoffValidator._entry_opacity_inside_story_window(
        {"initial": 0.14, "start": 10.0, "settle": 10.3}, cue)
    assert not LayerHandoffValidator._entry_opacity_inside_story_window(
        {"initial": 0.14, "start": 10.0, "settle": 11.7}, cue)
    assert not LayerHandoffValidator._entry_opacity_inside_story_window(
        {"initial": 0.14, "start": 10.0, "settle": 10.03}, cue)               # below two frames


def test_an_arrival_that_ended_on_the_last_keyframe_still_rests_until_progress_one() -> None:
    frames, _audit = bounded_entry([ARRIVAL[0], ARRIVAL[1], {**ARRIVAL[2], "progress": 1.0}], 1.6, ITEM)
    assert frames[-1]["progress"] == 1.0 and frames[-1]["scale"] == 1.0
    assert frames[-2]["progress"] * 1.6 == pytest.approx(13 / 30)
