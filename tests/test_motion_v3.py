from __future__ import annotations

import pytest

from app.models import CompositionBeat, LayoutItem, StoryBeat
from app.motion import MotionPlanner
from app.motion.easing import sample_easing
from app.motion.timing import MotionTimingPolicy


def _beat(
    *,
    beat_id: str = "beat-001",
    action: str = "INTRODUCE",
    narration: str = "clear explanation",
    start: float = 0.0,
    end: float = 2.0,
    audio_start: float = 0.24,
    audio_end: float = 1.8,
) -> StoryBeat:
    return StoryBeat(
        id=beat_id,
        scene_id="scene-001",
        start=start,
        end=end,
        audio_start=audio_start,
        audio_end=audio_end,
        narration=narration,
        primary_asset_ids=["primary"],
        support_asset_ids=["support"],
        action=action,
    )


def _composition(beat_id: str = "beat-001") -> CompositionBeat:
    return CompositionBeat(
        beat_id=beat_id,
        items=[
            LayoutItem(asset_id="primary", x=0.28, y=0.52, width=0.36, height=0.48, z=20),
            LayoutItem(asset_id="support", x=0.72, y=0.50, width=0.25, height=0.30, z=15),
        ],
    )


def test_motion_v3_is_backend_neutral_and_does_not_mutate_composition() -> None:
    beat = _beat(action="HANDOFF")
    composition = _composition()
    original = composition.model_dump()

    cues = MotionPlanner().plan([beat], [composition])

    assert composition.model_dump() == original
    assert len(cues) == 2
    assert all(cue.kind == "program_v3" for cue in cues)
    assert all(cue.params["engine_version"] == 3 for cue in cues)

    for cue in cues:
        keyframes = cue.params["program"]["keyframes"]
        assert keyframes[0]["progress"] == 0.0
        assert keyframes[-1]["progress"] == 1.0
        assert keyframes[-1]["dx"] == pytest.approx(0.0)
        assert keyframes[-1]["dy"] == pytest.approx(0.0)
        assert cue.start >= beat.start
        assert cue.end <= beat.end

    assert cues[1].start > cues[0].start


def test_result_program_contains_a_real_reaction_not_only_an_entrance() -> None:
    cues = MotionPlanner().plan([_beat(action="RESULT")], [_composition()])
    primary = cues[0]
    keyframes = primary.params["program"]["keyframes"]

    assert primary.params["program"]["name"] == "result_impact"
    assert len(keyframes) >= 5
    dx_values = [frame["dx"] for frame in keyframes]
    assert min(dx_values) < 0 < max(dx_values)


def test_fast_speech_compresses_motion_duration() -> None:
    policy = MotionTimingPolicy()
    slow = _beat(narration="two words")
    fast = _beat(narration="one two three four five six seven eight nine ten eleven twelve")

    slow_window = policy.window(beat=slow, distance=0.05, index=0, count=1, primary=True)
    fast_window = policy.window(beat=fast, distance=0.05, index=0, count=1, primary=True)

    assert fast_window.duration < slow_window.duration


@pytest.mark.parametrize(
    ("name", "expected_mid"),
    [
        ("linear", 0.5),
        ("smoothstep", 0.5),
        ("ease_in_out_cubic", 0.5),
    ],
)
def test_standard_easing_boundaries(name: str, expected_mid: float) -> None:
    assert sample_easing(name, 0.0) == pytest.approx(0.0)
    assert sample_easing(name, 0.5) == pytest.approx(expected_mid)
    assert sample_easing(name, 1.0) == pytest.approx(1.0)
