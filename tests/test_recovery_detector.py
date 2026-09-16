from app.models import MotionCue, RenderPlan, StoryBeat
from app.recovery.detector import RecoveryDetector


def _plan(cues: list[MotionCue]) -> RenderPlan:
    beat = StoryBeat(
        id="beat-001",
        scene_id="SCENE_001",
        start=0.70,
        end=2.50,
        audio_start=1.00,
        audio_end=2.20,
        narration="test",
        action="INTRODUCE",
    )
    return RenderPlan(
        width=854,
        height=480,
        fps=30,
        duration=2.5,
        story=[beat],
        composition=[],
        motion=cues,
        assets=[],
    )


def test_grouped_entrances_are_allowed_when_locked_to_narration() -> None:
    cues = [
        MotionCue(
            beat_id="beat-001",
            asset_id=f"a{index}",
            kind="reveal_in",
            start=0.72,
            end=end,
        )
        for index, end in enumerate((0.95, 1.02, 1.09), start=1)
    ]

    issues = RecoveryDetector().inspect_plan(_plan(cues))

    assert not any(issue.code == "MULTI_ELEMENT_POP" for issue in issues)


def test_grouped_entrances_still_fail_when_not_narration_locked() -> None:
    cues = [
        MotionCue(
            beat_id="beat-001",
            asset_id=f"a{index}",
            kind="reveal_in",
            start=1.45,
            end=1.80 + index * 0.01,
        )
        for index in range(1, 4)
    ]

    issues = RecoveryDetector().inspect_plan(_plan(cues))

    assert any(issue.code == "MULTI_ELEMENT_POP" for issue in issues)
