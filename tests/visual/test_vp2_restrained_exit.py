"""Visual Polish VP2-A: restrained outgoing exit inside a CRISP_HANDOFF (generic engine rules).

The exit only uses pre-opener time the outgoing scene no longer needs (Motion's own minimum
read hold after its last settle), lasts the certified EXIT comfort duration, ends on the
unchanged opener, staggers supporting visuals before the semantic result, keeps Pass2
families together, never fades and never clips; otherwise the handoff stays a clean cut.
"""
from __future__ import annotations

import shutil

import numpy as np
import pytest

from app.models import MotionCue
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


def test_exit_is_staggered_support_first_result_last_and_ends_on_the_opener() -> None:
    scene = _scene(16)
    row = scene.plan()
    assert row.mode == "CRISP_HANDOFF" and row.audit["opener_frame"] == 16
    exit_audit = row.audit["exit"]
    assert exit_audit["decision"] == "restrained_exit"
    assert exit_audit["exit_frames"] == round(0.40 * FPS)                  # EXIT comfort target
    assert exit_audit["order"] == [["old_b"], ["old_a"]]                  # SUPPORT, then RESULT
    starts = {asset: scene.frame(time) for asset, time in row.exit_starts.items()}
    assert starts == {"old_b": 16 - 12, "old_a": 16 - 12 + 2}
    assert row.release_start == row.release_end == row.opener_at          # opener never moves


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


def test_exit_offset_is_comfort_bounded_and_never_clips() -> None:
    scene = _scene(16)
    plan = scene.render_plan()
    near_edge = scene.composition[0].items[1].model_copy(update={"x": 0.88})  # 38 px of room
    for item in (scene.composition[0].items[1], near_edge):
        dx, dy = FFmpegRenderer._restrained_exit_offset(plan=plan, item=item, seconds=0.40)
        box_w, box_h, x, y = FFmpegRenderer._geometry(plan, item)
        assert 0 <= x + dx and x + box_w + dx <= plan.width and 0 <= y + dy and y + box_h + dy <= plan.height
        assert abs(dx) <= 0.14 * 0.40 * plan.width + 1 and abs(dy) <= 0.14 * 0.40 * plan.height + 1
    # Authored geometry already past the edge: the exit never pushes it further out.
    past_edge = scene.composition[0].items[1].model_copy(update={"x": 0.93})
    dx, _dy = FFmpegRenderer._restrained_exit_offset(plan=plan, item=past_edge, seconds=0.40)
    assert dx == 0


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg required")
def test_encoded_exit_is_opaque_moves_out_and_ends_on_the_opener(tmp_path) -> None:
    scene = _scene(16, root=tmp_path)
    row = scene.plan()
    frames = _encode(scene, [row], tmp_path / "exit")
    band = (slice(int(0.1 * 270), int(0.5 * 270)), slice(int(0.62 * 480), 480))   # old_b only
    b, opener = 60, 60 + 16
    mass, centre = [], []
    for k in range(b, opener + 1):
        dark = frames[k][band] < 128
        mass.append(int(dark.sum()))
        centre.append(float(np.nonzero(dark)[1].mean()) if dark.any() else None)
    reference = mass[0]
    assert reference > 0
    assert all(abs(m - reference) <= 0.12 * reference for m in mass[:-1])  # opaque: no fade
    moving = [c for c in centre[16 - 12:-1] if c is not None]
    assert all(right >= left - 0.5 for left, right in zip(moving, moving[1:]))
    assert moving[-1] - centre[0] >= 6                                      # visibly moved outward
    assert mass[-1] == 0                                                    # gone on the opener frame
    assert all(abs(c - centre[0]) < 0.5 for c in centre[:16 - 12] if c is not None)  # still before exit
    assert OLD_RIGHT  # geometry reference used by the band above
