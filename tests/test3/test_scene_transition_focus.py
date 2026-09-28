from __future__ import annotations

import itertools

import pytest

from app.models import AssetActivation, CompositionBeat, LayoutItem, StoryBeat
from app.render.renderer import FFmpegRenderer
from app.render.transition import SceneTransitionMode, VisualTransitionPolicy


def _layout(beat_id: str, *asset_ids: str) -> CompositionBeat:
    return CompositionBeat(
        beat_id=beat_id,
        items=[
            LayoutItem(
                asset_id=asset_id,
                x=0.2 + index * 0.2,
                y=0.5,
                width=0.16,
                height=0.24,
            )
            for index, asset_id in enumerate(asset_ids)
        ],
    )


def test_unrelated_scene_assets_release_by_incoming_first_focus() -> None:
    previous = StoryBeat(
        id="a", scene_id="scene-a", start=0.0, end=1.0,
        narration="system access", primary_asset_ids=["A1"], support_asset_ids=["A2"],
        action="EXPLAIN",
    )
    current = StoryBeat(
        id="b", scene_id="scene-b", start=1.0, end=3.0,
        narration="install", primary_asset_ids=["B1"], support_asset_ids=["B2"],
        action="INTRODUCE",
    )
    decision = VisualTransitionPolicy().decide(
        previous, _layout("a", "A1", "A2"), _layout("b", "B1", "B2"),
        current_beat=current,
    )
    assert decision.mode == SceneTransitionMode.MOTION_HANDOFF
    assert decision.carry_outgoing_asset_ids == frozenset({"A1", "A2"})
    start, end = FFmpegRenderer._scene_bridge_window(
        incoming_start=0.42,
        segment_duration=2.0,
        preferred_duration=decision.bridge_duration,
        allow_focus_overlap=False,
    )
    assert 0.0 <= start < end == pytest.approx(0.42)


def test_explicit_object_handoff_may_overlap_briefly_while_incoming_focus_wins() -> None:
    previous = StoryBeat(
        id="a", scene_id="scene-a", start=0.0, end=1.0,
        narration="source", primary_asset_ids=["carrier"], action="EXPLAIN",
        asset_activations=[AssetActivation(
            asset_id="carrier",
            semantic_unit_id="source-unit",
            continuity={"mode": "TRANSFORM_TO", "target_asset_id": "target-unit"},
        )],
    )
    current = StoryBeat(
        id="b", scene_id="scene-b", start=1.0, end=3.0,
        narration="target", primary_asset_ids=["target"], action="INTRODUCE",
        asset_activations=[AssetActivation(
            asset_id="target", semantic_unit_id="target-unit"
        )],
    )
    decision = VisualTransitionPolicy().decide(
        previous, _layout("a", "carrier"), _layout("b", "target"),
        current_beat=current,
    )
    assert decision.mode == SceneTransitionMode.OBJECT_HANDOFF
    assert decision.object_handoff_pairs == (("carrier", "target"),)
    start, end = FFmpegRenderer._scene_bridge_window(
        incoming_start=0.42,
        segment_duration=2.0,
        preferred_duration=decision.bridge_duration,
        allow_focus_overlap=True,
    )
    assert start < 0.42 < end
    assert end - 0.42 <= 0.32


def test_install_action_shape_has_one_initial_semantic_owner(tmp_path) -> None:
    # The prior scene is unrelated. Within the incoming scene, only the program owns
    # the first reveal; action support, target system, and direction arrive later.
    from tests.test3.test_semantic_reveal_focus import Spec, _certify, _focus

    specs = [
        Spec("program", "install", 0.35, "OBJECT"),
        Spec("action", "install", 0.82, "ACTION", False),
        Spec("target-system", "install", 1.24, "RESULT", False),
        Spec("direction", "install", 1.24, "SUPPORT", False),
    ]
    _story, motion, windows = _certify(
        tmp_path / "install-action-transition", specs, 2.5
    )
    first = min(windows, key=lambda asset_id: windows[asset_id].reveal_start)
    assert first == "program"
    focus = _focus(motion)
    assert focus["program"]["cohort_gain"] == pytest.approx(1.0)
    assert focus["action"]["cohort_role"] == "independent"
    assert sum(
        row["cohort_gain"] == pytest.approx(1.0)
        for asset_id, row in focus.items()
        if windows[asset_id].reveal_start == windows["program"].reveal_start
    ) == 1


def test_225_frame_quantized_transition_windows_have_no_ownership_gap() -> None:
    cases = 0
    for fps, mode, frame, fraction in itertools.product(
        (24, 25, 30, 50, 60),
        (SceneTransitionMode.MOTION_HANDOFF,
         SceneTransitionMode.OBJECT_HANDOFF,
         SceneTransitionMode.BLUR_BRIDGE),
        (1, 3, 9),
        (0.01, 0.50, 0.99, 1.0, 1.01),
    ):
        incoming = (frame + fraction) / fps
        allow_overlap = mode != SceneTransitionMode.MOTION_HANDOFF
        start, end = FFmpegRenderer._scene_bridge_window(
            incoming_start=incoming,
            segment_duration=1.0,
            preferred_duration=0.28,
            fps=fps,
            allow_focus_overlap=allow_overlap,
        )
        assert 0.0 <= start <= end <= 1.0
        if not allow_overlap:
            first_incoming_frame = FFmpegRenderer._frame_safe_bridge_end(
                incoming_start=incoming, segment_duration=1.0, fps=fps
            )
            assert end == pytest.approx(first_incoming_frame)
            assert 0.0 <= end - incoming <= 1.0 / fps + 1e-9
            previous_frame = max(0, int(first_incoming_frame * fps) - 1) / fps
            assert start <= previous_frame <= end
        cases += 1
    assert cases == 225
