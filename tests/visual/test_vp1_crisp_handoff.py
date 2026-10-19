"""Ordinary scene ownership transfers on the authored opener frame."""
from __future__ import annotations

import shutil

import pytest

from app.models import MotionSegment
from app.render.renderer import FFmpegRenderer
from app.render.transition import SceneTransitionMode
from tests.visual.test_sprint_4_5_scene_handoffs import (
    FPS, NEW_LATER, NEW_ON_OLD, OLD_LEFT, OLD_RIGHT, Scene, _darkness, _encode,
)


def _scene() -> Scene:
    scene = Scene(lead=10, opener=NEW_ON_OLD)
    scene.story[0] = scene.story[0].model_copy(update={
        "active_visual_semantic_state": {"old_a": "old_a", "old_b": "old_b"},
    })
    return scene


def test_explicit_outgoing_owner_is_crisp_until_existing_opener() -> None:
    scene = _scene()
    story_before = [beat.model_dump(mode="json") for beat in scene.story]
    motion_before = [cue.model_dump(mode="json") for cue in scene.motion]
    row = scene.plan()
    assert row.mode == "CRISP_HANDOFF"
    assert row.reason == "ordinary_scene_owner_until_opener"
    assert scene.frame(row.release_start) == scene.frame(row.release_end) == scene.frame(row.opener_at) == 10
    assert FFmpegRenderer._scene_release_window(
        plan=scene.render_plan([row]), beat=scene.story[1], previous_beat=scene.story[0],
        transition_mode=SceneTransitionMode.MOTION_HANDOFF, has_outgoing=True,
        incoming_start=10 / FPS, segment_start=2.0, frame_count=90,
    ) == pytest.approx((0.0, 0.0, 9.75 / FPS))
    assert story_before == [beat.model_dump(mode="json") for beat in scene.story]
    assert motion_before == [cue.model_dump(mode="json") for cue in scene.motion]


def test_preopener_text_keeps_prior_release_policy() -> None:
    scene = _scene()
    scene.add_text(5, 20, OLD_LEFT[0], OLD_LEFT[1])
    assert scene.plan().mode == "EXACT_END"


def test_preopener_protected_motion_keeps_prior_release_policy() -> None:
    scene = _scene()
    cue = scene.motion[2]
    scene.motion[2] = cue.model_copy(update={
        "segments": [MotionSegment(phase="EXIT", connection=True,
                                   start=2.0 + 5 / FPS, end=2.0 + 9 / FPS)],
    })
    assert scene.plan().mode == "EXACT_END"


def test_subframe_protected_start_on_opener_is_safe() -> None:
    scene = _scene()
    cue = scene.motion[2]
    scene.motion[2] = cue.model_copy(update={
        "segments": [MotionSegment(phase="PAYOFF", start=2.0 + 9.1 / FPS,
                                   end=2.0 + 11 / FPS)],
    })
    row = scene.plan()
    assert row.mode == "CRISP_HANDOFF"
    assert scene.frame(row.opener_at) == 10


@pytest.mark.parametrize("start_frames, mode", [
    (9.0001, "CRISP_HANDOFF"),  # first visible frame == opener (10): legal
    (9.0, "EXACT_END"),         # exactly frame 9: visible one frame before the opener
    (8.5, "EXACT_END"),         # first visible frame 9 < opener
])
def test_protected_motion_guard_uses_the_encoded_frame_grid(start_frames, mode) -> None:
    # A later incoming asset's protected connection (EXIT segments never define visibility,
    # so the opener itself stays on frame 10 whatever this action does).
    scene = _scene()
    cue = scene.motion[3]
    scene.motion[3] = cue.model_copy(update={
        "segments": [MotionSegment(phase="EXIT", connection=True, start=2.0 + start_frames / FPS,
                                   end=2.0 + 12 / FPS)],
    })
    row = scene.plan()
    assert row.audit["opener_frame"] == 10
    assert row.mode == mode


def test_crisp_handoff_never_moves_the_opener_or_any_motion() -> None:
    crisp_scene, exact_scene = _scene(), Scene(lead=10, opener=NEW_ON_OLD)
    crisp, exact = crisp_scene.plan(), exact_scene.plan()
    assert (crisp.mode, exact.mode) == ("CRISP_HANDOFF", "EXACT_END")
    assert crisp.opener_at == exact.opener_at == exact.release_end
    assert crisp.release_start == crisp.release_end == crisp.opener_at  # no release clock at all
    assert [c.model_dump() for c in crisp_scene.motion] == [c.model_dump() for c in exact_scene.motion]


def test_unfinished_outgoing_action_abstains() -> None:
    scene = _scene()
    cue = scene.motion[0]
    scene.motion[0] = cue.model_copy(update={
        "segments": [MotionSegment(phase="PAYOFF", start=1.9,
                                   end=2.0 + 8 / FPS)],
    })
    assert scene.plan().mode == "HARD_CUT"


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg required")
def test_encoded_crisp_handoff_preserves_old_art_and_does_not_reveal_early(tmp_path) -> None:
    scene = _scene()
    scene.assets = [asset.model_copy(update={"image_path": tmp_path / f"{asset.id}.png"})
                    for asset in scene.assets]
    crisp_row = scene.plan()
    crisp = _encode(scene, [crisp_row], tmp_path / "crisp")
    faded = _encode(scene, [crisp_row.model_copy(update={
        "mode": "EXACT_END", "reason": "comparison",
        "release_start": 2.0 + 4 / FPS, "release_end": 2.0 + 10 / FPS,
    })], tmp_path / "faded")
    assert crisp.shape == faded.shape
    for box in (OLD_LEFT, OLD_RIGHT):
        solid, ghost = _darkness(crisp, box), _darkness(faded, box)
        assert solid[60 + 8] > 0.97
        assert ghost[60 + 8] < solid[60 + 8] - 0.2
    assert _darkness(crisp, NEW_LATER)[60 + 9] == pytest.approx(0, abs=0.01)
    assert _darkness(crisp, OLD_RIGHT)[60 + 10] < 0.01
    assert abs(crisp[60 + 10:] - faded[60 + 10:]).mean() < 0.5


@pytest.fixture(autouse=True)
def _certified_boundary_machinery(monkeypatch):
    """These tests pin the hero-exit / crisp / cut machinery the scene whip falls back to."""
    import app.boundary.release as release

    monkeypatch.setattr(release, "SCENE_WHIP", False)
