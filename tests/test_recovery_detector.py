from app.models import MotionCue, RenderPlan, StoryBeat
from app.story.windows import StoryAssetActivation
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


def test_story_v2_primary_can_settle_on_later_phrase_without_legacy_late_issue() -> None:
    beat = StoryBeat(
        id="beat-001", scene_id="SCENE_001", start=0.70, end=2.50,
        audio_start=1.00, audio_end=2.20, narration="test", action="INTRODUCE",
        primary_asset_ids=["a1"],
        asset_activations=[StoryAssetActivation(
            asset_id="a1", spoken_start=1.55, spoken_end=1.90,
            phrase_start=1.55, phrase_end=1.90, reveal_start=1.45,
            semantic_peak=1.72, settle_at=1.90,
            policy="SEMANTIC", activation_policy="OWN_WINDOW",
            confidence=0.95, source="multilingual_semantic_match",
        )],
    )
    cue = MotionCue(
        beat_id="beat-001", asset_id="a1", kind="program_v3",
        start=1.45, end=1.90, params={"semantic_settle_time": 1.90},
    )
    plan = RenderPlan(
        width=854, height=480, fps=30, duration=2.5, story=[beat],
        composition=[], motion=[cue], assets=[],
    )

    issues = RecoveryDetector().inspect_plan(plan)

    assert not any(issue.code in {"ELEMENT_APPEARS_TOO_LATE", "ELEMENT_APPEARS_TOO_EARLY"}
                   for issue in issues)


def test_legacy_primary_still_uses_audio_start_recovery_heuristic() -> None:
    beat = StoryBeat(
        id="beat-001", scene_id="SCENE_001", start=0.70, end=2.50,
        audio_start=1.00, audio_end=2.20, narration="test", action="INTRODUCE",
        primary_asset_ids=["a1"],
    )
    cue = MotionCue(
        beat_id="beat-001", asset_id="a1", kind="program_v3",
        start=1.45, end=1.90, params={"semantic_settle_time": 1.90},
    )
    plan = RenderPlan(
        width=854, height=480, fps=30, duration=2.5, story=[beat],
        composition=[], motion=[cue], assets=[],
    )

    issues = RecoveryDetector().inspect_plan(plan)

    assert any(issue.code == "ELEMENT_APPEARS_TOO_LATE" for issue in issues)


def test_semantic_binding_group_is_not_treated_as_multi_element_pop() -> None:
    beat = StoryBeat(
        id="beat-001", scene_id="SCENE_001", start=0.10, end=3.00,
        audio_start=0.10, audio_end=3.00, narration="test", action="INTRODUCE",
        asset_activations=[
            StoryAssetActivation(
                asset_id=f"a{index}", spoken_start=0.10, spoken_end=2.40,
                phrase_start=0.10, phrase_end=2.40, reveal_start=0.10,
                semantic_peak=1.25, settle_at=2.40, policy="EXPLICIT",
                activation_policy="OWN_WINDOW", confidence=1.0,
                source="final_package_semantic_binding",
            )
            for index in range(1, 5)
        ],
    )
    cues = [
        MotionCue(
            beat_id="beat-001", asset_id=f"a{index}", kind="program_v3",
            start=0.10, end=2.40, params={"semantic_settle_time": 2.40},
        )
        for index in range(1, 5)
    ]
    plan = RenderPlan(
        width=854, height=480, fps=30, duration=3.0, story=[beat],
        composition=[], motion=cues, assets=[],
    )

    issues = RecoveryDetector().inspect_plan(plan)

    assert not any(issue.code == "MULTI_ELEMENT_POP" for issue in issues)


def test_partial_semantic_binding_group_still_detects_multi_element_pop() -> None:
    beat = StoryBeat(
        id="beat-001", scene_id="SCENE_001", start=0.10, end=3.00,
        audio_start=0.10, audio_end=3.00, narration="test", action="INTRODUCE",
        asset_activations=[StoryAssetActivation(
            asset_id="a1", spoken_start=0.10, spoken_end=2.40,
            phrase_start=0.10, phrase_end=2.40, reveal_start=0.10,
            semantic_peak=1.25, settle_at=2.40, policy="EXPLICIT",
            activation_policy="OWN_WINDOW", confidence=1.0,
            source="final_package_semantic_binding",
        )],
    )
    cues = [
        MotionCue(
            beat_id="beat-001", asset_id=f"a{index}", kind="program_v3",
            start=0.10, end=2.40, params={"semantic_settle_time": 2.40},
        )
        for index in range(1, 4)
    ]
    plan = RenderPlan(
        width=854, height=480, fps=30, duration=3.0, story=[beat],
        composition=[], motion=cues, assets=[],
    )

    issues = RecoveryDetector().inspect_plan(plan)

    assert any(issue.code == "MULTI_ELEMENT_POP" for issue in issues)
