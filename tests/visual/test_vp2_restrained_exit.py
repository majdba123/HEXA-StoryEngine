"""Outgoing exits inside a CRISP_HANDOFF (VP2-A, completed by Cinematic VNext2).

The exit only uses pre-opener time the outgoing scene no longer needs (Motion's own minimum
read hold after its last settle) and ends on the unchanged opener. VNext2: an exit is
planned only when it can finish - the unit leaves the frame completely through its nearest
side edge within the HERO_TRAVEL speed cap - so nothing vanishes halfway through an exit
(the former restrained drift moved a few pixels and was then cut). A unit that cannot
leave in time stays still and leaves with the opener (clean cut). Pass2 families leave as
one unit; an exit never fades.
"""
from __future__ import annotations

import shutil

import numpy as np
import pytest

from app.models import MotionCue
from app.motion.hero_travel import HERO_TRAVEL, SMOOTHSTEP_PEAK
from app.render.renderer import FFmpegRenderer
from tests.visual.test_sprint_4_5_scene_handoffs import FPS, NEW_ON_OLD, OLD_RIGHT, Scene, _encode


def _with_focus(cue: MotionCue, *, hold_ms: int | None = 250, focus: str = "SUPPORT") -> MotionCue:
    params = dict(cue.params)
    semantic = {"visual_focus": focus, "role": focus}
    if hold_ms is not None:
        semantic["rhythm"] = {"minimum_read_hold_ms": hold_ms}
    params["semantic_focus"] = semantic
    return cue.model_copy(update={"params": params})


def _scene(lead: int, *, hold_ms: int | None = 250, old_a: str = "RESULT", old_b: str = "SUPPORT",
           old_end: float | None = None, root=None) -> Scene:
    scene = Scene(lead=lead, opener=NEW_ON_OLD, later=60, root=root)
    scene.story[0] = scene.story[0].model_copy(update={
        "active_visual_semantic_state": {"old_a": "old_a", "old_b": "old_b"}})
    focus = {"old_a": old_a, "old_b": old_b}
    for index, cue in enumerate(scene.motion):
        if cue.beat_id == "b1":
            cue = _with_focus(cue, hold_ms=hold_ms, focus=focus[cue.asset_id])
            if old_end is not None and cue.asset_id == "old_b":
                cue = cue.model_copy(update={"end": old_end})
            scene.motion[index] = cue
    return scene


def test_exit_needs_motion_read_hold_authority() -> None:
    row = _scene(16, hold_ms=None).plan()
    assert row.mode == "CRISP_HANDOFF" and row.exit_starts == {}
    assert row.audit["exit"]["decision"] == "abstain:no_motion_read_hold_authority"


# Both fixture units sit 0.31 frame widths (margin included) from their nearest side edge.
_EXIT_FRAMES = 14  # ceil(30 * max(0.40, 1.5 * 0.31 / 1.0))


def test_an_exit_is_planned_only_when_the_unit_can_leave_the_frame_and_ends_on_the_opener() -> None:
    scene = _scene(16)
    row = scene.plan()
    assert row.mode == "CRISP_HANDOFF" and row.audit["opener_frame"] == 16
    exit_audit = row.audit["exit"]
    assert exit_audit["decision"] == "complete_exit"
    assert exit_audit["order"] == [["old_b"]]                             # the SUPPORT unit leaves
    assert exit_audit["clean_cut_units"] == [["old_a"]]                   # the RESULT covers to the cut
    starts = {asset: scene.frame(time) for asset, time in row.exit_starts.items()}
    assert starts == {"old_b": 16 - _EXIT_FRAMES}
    distance = 1 - (0.8 - 0.2 / 2) + 0.01
    assert _EXIT_FRAMES / FPS >= SMOOTHSTEP_PEAK * distance / HERO_TRAVEL.max_normalized_speed - 1e-9
    assert row.release_start == row.release_end == row.opener_at          # opener never moves


def test_a_unit_that_cannot_leave_in_time_stays_still_for_a_clean_cut() -> None:
    row = _scene(13).plan()                                               # 13 < 14 frames needed
    assert row.mode == "CRISP_HANDOFF" and row.exit_starts == {}
    assert row.audit["exit"]["decision"] == "clean_cut:exit_cannot_leave_the_frame_in_time"
    assert row.audit["exit"]["clean_cut_units"] == [["old_b"], ["old_a"]]


def test_too_little_time_keeps_a_clean_cut() -> None:
    row = _scene(8).plan()                                                # < EXIT minimum 0.32 s
    assert row.mode == "CRISP_HANDOFF" and row.exit_starts == {}
    assert row.audit["exit"]["decision"] == "clean_cut:insufficient_time_after_read_hold"


def test_exit_waits_for_the_outgoing_read_hold() -> None:
    # The last outgoing motion settles just before the cut; with a 250 ms read hold only
    # a few pre-opener frames remain, so the scene is not moved before it can be read.
    row = _scene(16, old_end=2.0 - 1 / FPS).plan()
    assert row.audit["exit"]["decision"] == "clean_cut:insufficient_time_after_read_hold"
    assert row.exit_starts == {}


def test_pass2_family_leaves_as_one_unit() -> None:
    scene = _scene(16)
    scene.assets = [asset.model_copy(update={"asset_family_id": "fam"}) if asset.id.startswith("old_")
                    else asset for asset in scene.assets]
    row = scene.plan()
    if row.mode == "CRISP_HANDOFF" and row.exit_starts:
        assert len(set(row.exit_starts.values())) == 1


def test_the_executed_exit_takes_the_cutout_completely_off_the_canvas_through_its_nearest_edge() -> None:
    scene = _scene(16)
    plan = scene.render_plan()
    old_a, old_b = scene.composition[0].items[0], scene.composition[0].items[1]
    for item, direction in ((old_a, -1), (old_b, 1)):
        dx = FFmpegRenderer._offcanvas_exit_offset(plan=plan, item=item)
        box_w, _box_h, x, _y = FFmpegRenderer._geometry(plan, item)
        assert dx * direction > 0
        assert (x + box_w + dx <= 0) if direction < 0 else (x + dx >= plan.width)


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg required")
def test_encoded_exit_is_opaque_and_leaves_the_canvas_before_it_is_removed(tmp_path) -> None:
    scene = _scene(16, root=tmp_path)
    row = scene.plan()
    frames = _encode(scene, [row], tmp_path / "exit")
    band = (slice(int(0.1 * 270), int(0.5 * 270)), slice(int(0.62 * 480), 480))   # old_b's side
    b, opener = 60, 60 + 16
    begin = 16 - _EXIT_FRAMES
    mass, centre = [], []
    for k in range(b, opener + 1):
        dark = frames[k][band] < 128
        mass.append(int(dark.sum()))
        centre.append(float(np.nonzero(dark)[1].mean()) if dark.any() else None)
    reference = mass[0]
    assert reference > 0
    assert all(abs(m - reference) <= 0.12 * reference for m in mass[:begin + 1])  # opaque, still
    assert all(abs(c - centre[0]) < 0.5 for c in centre[:begin + 1] if c is not None)
    # It travels outward and the visible part only shrinks as it crosses the edge (no fade).
    assert all(right <= left + 0.02 * reference for left, right in zip(mass[begin:], mass[begin + 1:]))
    moving = [c for c in centre[begin:] if c is not None]
    assert all(right >= left - 0.5 for left, right in zip(moving, moving[1:]))
    # Completely off the canvas on the last frame before the opener: nothing vanishes in view.
    assert mass[-2] <= 0.02 * reference and mass[-1] == 0
    assert OLD_RIGHT  # geometry reference used by the band above
