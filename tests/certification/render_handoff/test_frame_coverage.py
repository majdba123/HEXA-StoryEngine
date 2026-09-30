"""Structural handoff-coverage certification on the encoded frame grid.

Every internal handoff must leave no frame without an owner:

    outgoing cover (bridge)  U  incoming artwork  covers every frame of the window

and the incoming artwork must become visible on exactly the frame Story's continuous
reveal time maps to (never earlier: no future semantic reveal).

Generated groups (deterministic, overlap by design):
  500 boundary timing variants          (fps x boundary x reveal decimal)
  200 transition-mode variants          (mode x fps x reveal)
  200 persistent / non-persistent       (coverage requirement and carrier choice)
  200 delayed incoming reveals
  100 object handoffs
  100 short-beat / frame-budget cases
"""

from __future__ import annotations

import itertools
import random

import pytest

from app.models import MotionCue, StoryBeat
from app.render.renderer import FFmpegRenderer
from app.render.transition import SceneTransitionMode
from app.shared.errors import StageFailedError

from .frame_model import (
    covered_frames_until,
    first_frame_at_or_after,
    visible_frames_from,
)

FPS_SET = (24, 25, 30, 50, 60)
MODES = (
    SceneTransitionMode.MOTION_HANDOFF,
    SceneTransitionMode.OBJECT_HANDOFF,
    SceneTransitionMode.BLUR_BRIDGE,
)


def _window(fps: int, boundary: float, reveal: float, total: float, mode, preferred=0.3):
    """Segment-local bridge and reveal exactly as _render_beat_segment derives them."""
    frames = max(2, round(total * fps))
    segment_start = round(boundary * fps) / fps
    duration = frames / fps
    incoming = max(0.0, reveal - segment_start)
    start, end = FFmpegRenderer._scene_bridge_window(
        incoming_start=incoming, segment_duration=duration, preferred_duration=preferred,
        fps=fps, allow_focus_overlap=mode != SceneTransitionMode.MOTION_HANDOFF,
    )
    threshold = FFmpegRenderer._frame_safe_reveal_threshold(incoming, fps)
    return frames, duration, incoming, start, end, threshold


def _assert_no_blank_frame(fps, frames, incoming, end, threshold):
    covered = covered_frames_until(end, frames, fps)
    visible = visible_frames_from(threshold, frames, fps)
    blank = [n for n in range(frames) if n not in covered and n not in visible]
    assert blank == [], f"blank frames {blank} (incoming={incoming}, end={end}, thr={threshold})"
    # The incoming artwork starts on Story's first encoded frame, never before it.
    first = first_frame_at_or_after(incoming, fps)
    if first < frames:
        assert min(visible) == first, (min(visible), first)


_rng = random.Random(20261001)
BOUNDARY = [
    (fps, _rng.choice((0.0, 0.42, 0.5, 1.0, 11.42, 11.4333333, 27.165)),
     _rng.choice((0, 1, 2, 3, 4, 5, 6, 7, 9)) + _rng.choice((0.0, 0.0, 1e-7, -1e-7, 0.5, 0.25, 0.999999, 1.000001)),
     _rng.choice(MODES))
    for fps in FPS_SET for _ in range(100)
]


@pytest.mark.parametrize(("fps", "boundary", "reveal_frames", "mode"), BOUNDARY)
def test_boundary_timing_variants_leave_no_blank_frame(fps, boundary, reveal_frames, mode) -> None:
    segment_start = round(boundary * fps) / fps
    reveal = segment_start + max(0.0, reveal_frames) / fps
    frames, _d, incoming, _s, end, threshold = _window(fps, boundary, reveal, 1.6, mode)
    _assert_no_blank_frame(fps, frames, incoming, end, threshold)


@pytest.mark.parametrize(("fps", "mode", "frame", "fraction"), [
    (fps, mode, frame, fraction)
    for fps, mode, frame, fraction in itertools.product(
        FPS_SET, MODES, (1, 2, 3, 5, 9),
        (0.0, 1e-6, 0.01, 0.25, 0.5, 0.75, 0.99, 1.0 - 1e-6),
    )
])
def test_transition_mode_variants_leave_no_blank_frame(fps, mode, frame, fraction) -> None:
    incoming = (frame + fraction) / fps
    frames = round(1.0 * fps)
    start, end = FFmpegRenderer._scene_bridge_window(
        incoming_start=incoming, segment_duration=1.0, preferred_duration=0.3, fps=fps,
        allow_focus_overlap=mode != SceneTransitionMode.MOTION_HANDOFF,
    )
    threshold = FFmpegRenderer._frame_safe_reveal_threshold(incoming, fps)
    _assert_no_blank_frame(fps, frames, incoming, end, threshold)
    assert 0.0 <= start <= end <= 1.0 + 1e-9


DELAYED = [(fps, delay) for fps in FPS_SET for delay in
           [round(0.05 + 0.0737 * i, 4) for i in range(40)]]


@pytest.mark.parametrize(("fps", "delay"), DELAYED)
def test_delayed_incoming_reveal_is_covered_until_its_own_frame_not_earlier(fps, delay) -> None:
    """A late semantic reveal is never pulled forward to close a gap."""
    frames = round(2.5 * fps)
    incoming = delay
    start, end = FFmpegRenderer._scene_bridge_window(
        incoming_start=incoming, segment_duration=2.5, preferred_duration=0.3, fps=fps,
        allow_focus_overlap=False,
    )
    threshold = FFmpegRenderer._frame_safe_reveal_threshold(incoming, fps)
    visible = visible_frames_from(threshold, frames, fps)
    if not visible:  # reveal falls after the segment's last frame: nothing to show yet
        assert first_frame_at_or_after(incoming, fps) >= frames
        return
    assert min(visible) == first_frame_at_or_after(incoming, fps)
    assert all(n / fps >= incoming - 1 / fps for n in visible)  # nothing earlier than its frame
    _assert_no_blank_frame(fps, frames, incoming, end, threshold)


@pytest.mark.parametrize(("fps", "frames", "reveal_frame"), [
    (fps, frames, reveal)
    for fps in FPS_SET for frames in (2, 3, 4, 5, 6, 8) for reveal in range(1, frames)
][:100])
def test_short_beats_keep_the_frame_budget_and_coverage(fps, frames, reveal_frame) -> None:
    duration = frames / fps
    incoming = reveal_frame / fps
    start, end = FFmpegRenderer._scene_bridge_window(
        incoming_start=incoming, segment_duration=duration, preferred_duration=0.3, fps=fps,
        allow_focus_overlap=False,
    )
    threshold = FFmpegRenderer._frame_safe_reveal_threshold(incoming, fps)
    assert 0.0 <= start <= end <= duration + 1e-9
    _assert_no_blank_frame(fps, frames, incoming, end, threshold)


# ------------------------------------------------ reveal thresholds and ordering


@pytest.mark.parametrize("fps", FPS_SET)
@pytest.mark.parametrize("frame", range(0, 40))
def test_threshold_makes_exactly_the_target_frame_the_first_visible_one(fps, frame) -> None:
    for offset in (0.0, -1e-9, 1e-9, -1e-7, 0.3 / fps, -0.3 / fps, -0.99 / fps):
        start = frame / fps + offset
        if start < 0:
            continue
        expected = first_frame_at_or_after(start, fps)
        threshold = FFmpegRenderer._frame_safe_reveal_threshold(start, fps)
        visible = visible_frames_from(threshold, frame + 3, fps)
        assert min(visible) == expected


def test_grouped_reveals_keep_order_and_use_the_same_threshold() -> None:
    rows = [("a", 5 / 30, {"semantic_group_id": "g", "sequence_order": 1}),
            ("b", 5 / 30 + 1e-7, {"semantic_group_id": "g", "sequence_order": 2}),
            ("c", 9 / 30, {"semantic_group_id": "g", "sequence_order": 3}),
            ("solo", 7 / 30, {})]
    out = FFmpegRenderer._frame_safe_group_reveal_starts(rows=rows, fps=30, duration=1.0)
    first = {k: min(visible_frames_from(v, 30, 30)) for k, v in out.items()}
    assert first["a"] == 5 and first["b"] == 6 and first["c"] == 9  # order preserved, never earlier
    assert first["solo"] == 7  # ungrouped reveals are quantized too


# ------------------------------------------------------ persistent / carriers


def _cue(beat: str, asset: str, start: float, **focus) -> MotionCue:
    params = {"semantic_focus": focus, "motion_order": {"sequence_order": int(start * 100)}}
    return MotionCue(beat_id=beat, asset_id=asset, kind="reveal_in", start=start,
                     end=start + 0.2, params=params)


class _Item:
    def __init__(self, asset_id: str, area: float = 0.04) -> None:
        self.asset_id, self.width, self.height = asset_id, area ** 0.5, area ** 0.5


ROLES = ("CONTEXT", "OBJECT", "CHARACTER", "SUPPORT", "ACTION", "PRIMARY", "RESULT")


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("delay", [0.05, 0.3, 0.84, 1.5])
@pytest.mark.parametrize("persistent", [False, True])
def test_no_carrier_ever_exposes_content_before_its_story_reveal(role, delay, persistent) -> None:
    """A beat whose earliest reveal is after its start never gets a boundary carrier."""
    beat = StoryBeat(id="b", scene_id="s", start=0.0, end=4.0, narration="n", action="INTRODUCE")
    items = [_Item("first"), _Item("later", 0.09)]
    motion = {("b", "first"): _cue("b", "first", delay, semantic_role=role),
              ("b", "later"): _cue("b", "later", delay + 1.2, semantic_role="CONTEXT")}
    assert FFmpegRenderer._visual_carrier_asset_id(
        beat=beat, ordered_items=items, motion=motion,
        persistent_ids=frozenset({"x"}) if persistent else frozenset(),
    ) is None


@pytest.mark.parametrize("role", ROLES)
def test_boundary_carrier_is_never_a_later_revealed_asset(role) -> None:
    """With an asset revealed exactly at the beat start, a later-revealed asset (future
    semantics) is outside the earliest cohort and is never chosen."""
    beat = StoryBeat(id="b", scene_id="s", start=1.0, end=4.0, narration="n", action="INTRODUCE")
    items = [_Item("now"), _Item("later", 0.16)]
    motion = {("b", "now"): _cue("b", "now", 1.0, semantic_role=role),
              ("b", "later"): _cue("b", "later", 2.4, semantic_role="CONTEXT")}
    assert FFmpegRenderer._visual_carrier_asset_id(
        beat=beat, ordered_items=items, motion=motion, persistent_ids=frozenset(),
    ) == "now"


def test_persistent_assets_suppress_any_carrier_and_any_coverage_error() -> None:
    beat = StoryBeat(id="b", scene_id="s", start=1.0, end=4.0, narration="n", action="INTRODUCE")
    items = [_Item("first")]
    motion = {("b", "first"): _cue("b", "first", 1.0, semantic_role="OBJECT")}
    assert FFmpegRenderer._visual_carrier_asset_id(
        beat=beat, ordered_items=items, motion=motion, persistent_ids=frozenset({"x"}),
    ) is None
    FFmpegRenderer._require_handoff_coverage(
        beat=beat, is_opening=False, ordered_items=items, persistent_ids=frozenset({"x"}),
        covered=False, incoming_start=0.9, fps=30,
    )


COVERAGE = [
    (fps, opening, frames, covered)
    for fps in FPS_SET for opening in (True, False) for frames in range(0, 12)
    for covered in (False, True)
]


@pytest.mark.parametrize(("fps", "opening", "blank", "covered"), COVERAGE)
def test_uncovered_internal_blank_frames_fail_before_ffmpeg_with_a_typed_code(
    fps, opening, blank, covered,
):
    beat = StoryBeat(id="b", scene_id="s", start=0.0, end=4.0, narration="n", action="INTRODUCE")
    incoming = (blank - 0.5) / fps if blank else 0.0  # ``blank`` frames precede the reveal
    call = dict(beat=beat, is_opening=opening, ordered_items=[_Item("a")],
                persistent_ids=frozenset(), covered=covered, incoming_start=incoming, fps=fps)
    if opening or covered or blank == 0:  # the opening is judged by the encoded verifier
        FFmpegRenderer._require_handoff_coverage(**call)
    else:
        with pytest.raises(StageFailedError) as info:
            FFmpegRenderer._require_handoff_coverage(**call)
        assert info.value.effective_code == "VISUAL_HANDOFF_COVERAGE_INFEASIBLE"
        assert info.value.details["blank_frames"] == blank and not info.value.details["opening"]
