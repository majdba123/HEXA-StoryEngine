"""Over-segmented authored units must fit the encoded frame budget.

Regression for real packages whose single authored unit (footprints, a person with
many keys) was segmented into 8-10 cutouts inside a ~5-7 frame Story window: the
internal geometric stagger produced sub-frame reveal instants that the renderer's
frame quantizer pushed past each member's entry window.
"""

from __future__ import annotations

import math

import pytest

from app.motion.timing import MotionTimingPolicy, MotionWindow

FPS = 30


@pytest.mark.parametrize("count", [2, 3, 5, 8, 10, 16])
@pytest.mark.parametrize("span", [0.12, 0.16, 0.225, 0.40, 0.80])
def test_visual_unit_stagger_never_exceeds_frame_budget(count: int, span: float) -> None:
    window = MotionWindow(start=66.24, end=66.24 + span, semantic_settle=66.24 + span,
                          pace_tier="normal", semantic_peak=66.24 + span / 2, story_v2=True)
    rows = [
        MotionTimingPolicy._stagger_visual_unit_window(window, index=index, count=count)
        for index in range(count)
    ]

    starts = sorted({row.start for row in rows})
    frames = [math.ceil(start * FPS - 1e-9) for start in starts]
    # Every distinct reveal instant lands on its own encoded frame ...
    assert len(set(frames)) == len(frames)
    # ... inside the Story window, with every member's entry keeping a legal frame.
    assert all(window.start - 1e-9 <= row.start and row.end <= window.end + 1e-9 for row in rows)
    for row in rows:
        first_visible = math.ceil(row.start * FPS - 1e-9) / FPS
        assert first_visible < row.end + 1e-9 or row.end - row.start < 1 / FPS
    # Geometric order is preserved: member order never goes backwards.
    assert [row.start for row in rows] == sorted(row.start for row in rows)


def test_feasible_stagger_is_unchanged_one_start_per_member() -> None:
    window = MotionWindow(start=10.0, end=11.2, semantic_settle=11.2, pace_tier="normal",
                          story_v2=True)
    rows = [
        MotionTimingPolicy._stagger_visual_unit_window(window, index=index, count=4)
        for index in range(4)
    ]
    assert len({row.start for row in rows}) == 4
    assert rows[-1].end == window.end


def test_compiled_entry_recap_removes_post_retime_speed_spike() -> None:
    """Peak retiming can squeeze a return leg into milliseconds after the pre-compile cap."""
    from app.models import LayoutItem, MotionCue
    from app.motion import MotionPlanner
    from app.motion.timing import motion_comfort

    keyframes = [
        {"progress": 0.0, "dx": 0.0, "dy": 0.0019, "scale": 0.995, "easing": "ease_in_out_cubic"},
        {"progress": 0.9658, "dx": 0.0015, "dy": -0.0024, "scale": 1.0057, "easing": "ease_out_cubic"},
        {"progress": 1.0, "dx": 0.0, "dy": 0.0, "scale": 1.0, "easing": "ease_out_cubic"},
    ]
    cue = MotionCue(
        beat_id="beat", asset_id="asset", kind="program_v3", start=78.84, end=78.922,
        params={"program": {"name": "pop", "settle_progress": 1.0, "keyframes": keyframes}},
    )
    item = LayoutItem(asset_id="asset", x=0.5, y=0.5, width=0.2, height=0.3)
    recapped = MotionPlanner._recap_compiled_base_entry(cue, item=item)

    frames = recapped.params["program"]["keyframes"]
    duration = cue.end - cue.start
    limit = motion_comfort("ENTRY").max_normalized_speed
    for left, right in zip(frames, frames[1:]):
        seconds = max(1e-6, (right["progress"] - left["progress"]) * duration)
        translation = math.hypot(right["dx"] - left["dx"], right["dy"] - left["dy"])
        assert translation / seconds <= limit + 1e-9
    assert [row["progress"] for row in frames] == [row["progress"] for row in keyframes]
    assert (recapped.start, recapped.end) == (cue.start, cue.end)