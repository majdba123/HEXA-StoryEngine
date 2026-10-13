"""Visual Polish VP2-C: reserve Rhythm's read hold before the cut."""
from __future__ import annotations

from app.models import StoryBeat
from app.motion.timing import MotionTimingPolicy, MotionWindow, motion_comfort

BEAT = StoryBeat(id="b", scene_id="s", start=0.0, end=2.0, narration="x", action="REVEAL")
ENTRY_MIN = motion_comfort("ENTRY").minimum_seconds


# VP2-C -----------------------------------------------------------------------------------------
def test_window_touching_the_cut_reserves_the_read_hold_without_moving_its_start() -> None:
    window = MotionWindow(start=1.40, end=2.0, semantic_settle=2.0, pace_tier="balanced", semantic_peak=1.8)
    held = MotionTimingPolicy.reserve_read_hold(window, beat=BEAT, hold=0.25)
    assert held.start == window.start and held.end == 1.75
    assert held.semantic_settle == 1.75
    assert window.start < held.semantic_peak < held.end            # peak never collides with the end
    assert abs((held.semantic_peak - held.start) / (held.end - held.start) - 0.4 / 0.6) < 1e-9


def test_window_already_reading_is_untouched() -> None:
    window = MotionWindow(start=0.5, end=1.2, semantic_settle=1.0, pace_tier="balanced")
    assert MotionTimingPolicy.reserve_read_hold(window, beat=BEAT, hold=0.25) is window


def test_late_reveal_keeps_the_entry_comfort_minimum() -> None:
    window = MotionWindow(start=1.65, end=2.0, semantic_settle=2.0, pace_tier="snap")
    held = MotionTimingPolicy.reserve_read_hold(window, beat=BEAT, hold=0.25)
    assert held.start == 1.65 and abs((held.end - held.start) - ENTRY_MIN) < 1e-9


def test_no_room_degrades_gracefully_to_the_authored_window() -> None:
    window = MotionWindow(start=1.80, end=2.0, semantic_settle=2.0, pace_tier="snap")
    assert MotionTimingPolicy.reserve_read_hold(window, beat=BEAT, hold=0.25) is window
