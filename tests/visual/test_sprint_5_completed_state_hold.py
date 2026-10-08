"""A proven late semantic state stays readable until the unchanged next opener."""
from __future__ import annotations

import shutil

import pytest

from app.models import MotionSegment
from app.render.renderer import FFmpegRenderer
from app.render.transition import SceneTransitionMode
from tests.visual.test_sprint_4_5_scene_handoffs import (
    FPS, NEW_ON_OLD, OLD_LEFT, OLD_RIGHT, Scene, _darkness, _encode,
)


def _late_state(*, hold_ms: int = 300, active: bool = True) -> Scene:
    scene = Scene(lead=10, opener=NEW_ON_OLD)
    cue = scene.motion[1]
    scene.motion[1] = cue.model_copy(update={
        "start": 1.73,
        "end": 1.98,
        "params": {
            **cue.params,
            "semantic_focus": {
                "active": active,
                "role": "RESULT",
                "semantic_event_id": "authored-result",
                "rhythm": {"minimum_read_hold_ms": hold_ms},
            },
        },
    })
    return scene


def test_late_result_holds_to_existing_opener_without_moving_story_or_motion() -> None:
    scene = _late_state()
    before = [cue.model_dump(mode="json") for cue in scene.motion]
    row = scene.plan()
    assert row.mode == "HOLD_TO_OPENER"
    assert (scene.frame(row.release_start), scene.frame(row.release_end),
            scene.frame(row.opener_at)) == (10, 10, 10)
    assert row.audit["protected_asset_id"] == "old_b"
    assert row.audit["stable_frames_before_release"] < row.audit["required_stable_frames"]
    assert row.audit["stable_frames_to_opener"] >= row.audit["required_stable_frames"]
    assert before == [cue.model_dump(mode="json") for cue in scene.motion]
    assert FFmpegRenderer._scene_release_window(
        plan=scene.render_plan([row]), beat=scene.story[1], previous_beat=scene.story[0],
        transition_mode=SceneTransitionMode.MOTION_HANDOFF, has_outgoing=True,
        incoming_start=10 / FPS, segment_start=2.0, frame_count=90,
    ) == pytest.approx((0.0, 0.0, 9.75 / FPS))


def test_hold_abstains_without_proven_focus_or_when_reference_release_is_comfortable() -> None:
    assert _late_state(active=False).plan().mode == "EXACT_END"
    assert _late_state(hold_ms=100).plan().mode == "EXACT_END"
    assert _late_state(hold_ms=True).plan().mode == "EXACT_END"
    assert _late_state(hold_ms=10**1000).plan().mode == "EXACT_END"


def test_hold_abstains_for_text_or_protected_action_visible_before_opener() -> None:
    scene = _late_state()
    scene.add_text(5, 20, OLD_LEFT[0], OLD_LEFT[1])
    assert scene.plan().mode == "EXACT_END"

    scene = _late_state()
    next_cue = scene.motion[2]
    scene.motion[2] = next_cue.model_copy(update={
        "segments": [MotionSegment(
            phase="INTERACT", start=2.0 + 5 / FPS, end=2.0 + 15 / FPS,
        )],
    })
    assert scene.plan().mode == "EXACT_END"


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg required")
def test_encoded_hold_keeps_old_artwork_solid_then_cuts_on_original_opener(tmp_path) -> None:
    scene = _late_state()
    scene.assets = [a.model_copy(update={"image_path": tmp_path / f"{a.id}.png"})
                    for a in scene.assets]
    held = _encode(scene, [scene.plan()], tmp_path / "held")
    faded = _encode(scene, [scene.plan().model_copy(update={
        "mode": "EXACT_END", "reason": "baseline",
        "release_start": 2.0 + 4 / FPS, "release_end": 2.0 + 10 / FPS,
    })], tmp_path / "faded")
    assert held.shape == faded.shape == (150, 270, 480)
    for box in (OLD_LEFT, OLD_RIGHT):
        ink_held, ink_faded = _darkness(held, box), _darkness(faded, box)
        assert ink_held[60 + 8] > 0.97
        assert ink_faded[60 + 8] < ink_held[60 + 8] - 0.2
    assert _darkness(held, OLD_RIGHT)[60 + 10] < 0.01
    assert abs(held[60 + 10:] - faded[60 + 10:]).mean() < 0.5
    assert abs(_darkness(held, NEW_ON_OLD)[60 + 10]
               - _darkness(faded, NEW_ON_OLD)[60 + 10]) < 0.02
