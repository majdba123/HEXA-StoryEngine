from __future__ import annotations

import pytest

from app.models import AssetActivation, CompositionBeat, LayoutItem, MotionCue, StoryBeat
from app.motion import MotionPlanner
from app.story.sync_qa import StorySyncQA
from app.story.windows import schedule_windows


def _beat(*activations: AssetActivation) -> StoryBeat:
    return StoryBeat(
        id="beat-001",
        scene_id="scene-001",
        start=0.0,
        end=2.0,
        audio_start=0.2,
        audio_end=1.8,
        narration="test narration",
        primary_asset_ids=["a"],
        support_asset_ids=["b"],
        action="INTRODUCE",
        asset_activations=list(activations),
    )


def _cue(asset_id: str, settle: float) -> MotionCue:
    return MotionCue(
        beat_id="beat-001",
        asset_id=asset_id,
        kind="program_v3",
        start=max(0.0, settle - 0.3),
        end=min(2.0, settle + 0.2),
        params={"semantic_settle_time": settle},
    )


def test_story_sync_qa_accepts_exact_semantic_settle() -> None:
    activation = AssetActivation(
        asset_id="b",
        trigger_text="يفكر",
        spoken_start=1.2,
        spoken_end=1.4,
        confidence=0.92,
        source="multilingual_semantic_match",
        policy="SEMANTIC",
    )
    report = StorySyncQA().inspect(
        story=[_beat(activation)],
        motion=[_cue("b", 1.2)],
    )

    assert report.passed
    assert report.anchored_assets == 1
    assert report.semantic_assets == 1
    assert report.fallback_assets == 0
    assert report.max_settle_delta_seconds == pytest.approx(0.0)
    assert len(report.entries) == 1
    assert report.entries[0].trigger_text == "يفكر"
    assert report.entries[0].motion_settle == pytest.approx(1.2)
    assert report.entries[0].settle_delta_seconds == pytest.approx(0.0)


def test_story_sync_qa_rejects_late_motion_settle() -> None:
    activation = AssetActivation(
        asset_id="b",
        trigger_text="يفكر",
        spoken_start=1.2,
        spoken_end=1.4,
        confidence=0.92,
        source="multilingual_semantic_match",
        policy="SEMANTIC",
    )
    report = StorySyncQA().inspect(
        story=[_beat(activation)],
        motion=[_cue("b", 1.31)],
    )

    assert not report.passed
    assert report.max_settle_delta_seconds == pytest.approx(0.11)
    assert any("settle_delta=0.110" in row for row in report.violations)


def test_story_sync_qa_allows_conservative_fallback_without_fake_anchor() -> None:
    fallback = AssetActivation(
        asset_id="b",
        confidence=0.0,
        source="semantic_abstention",
        policy="FALLBACK",
    )
    report = StorySyncQA().inspect(
        story=[_beat(fallback)],
        motion=[_cue("b", 0.8)],
    )

    assert report.passed
    assert report.anchored_assets == 0
    assert report.fallback_assets == 1

def test_story_sync_qa_scopes_sequence_order_to_same_precise_trigger_cluster() -> None:
    beat = StoryBeat(
        id="beat-001",
        scene_id="scene-001",
        start=0.0,
        end=2.0,
        audio_start=0.0,
        audio_end=1.8,
        narration="early shared phrase then later concept",
        primary_asset_ids=["later"],
        support_asset_ids=["early-a", "early-b"],
        action="INTRODUCE",
    )
    raw = [
        AssetActivation(
            asset_id="later",
            spoken_start=1.10,
            spoken_end=1.45,
            trigger_char_start=20,
            trigger_char_end=33,
            confidence=1.0,
            source="final_package_semantic_binding",
            policy="EXPLICIT",
            semantic_group_id="g",
            sequence_order=1,
            group_animation_policy="SEQUENTIAL_WITHIN_PHRASE",
        ),
        AssetActivation(
            asset_id="early-a",
            spoken_start=0.25,
            spoken_end=0.80,
            trigger_char_start=0,
            trigger_char_end=18,
            confidence=1.0,
            source="final_package_semantic_binding",
            policy="EXPLICIT",
            semantic_group_id="g",
            sequence_order=2,
            group_animation_policy="SEQUENTIAL_WITHIN_PHRASE",
        ),
        AssetActivation(
            asset_id="early-b",
            spoken_start=0.25,
            spoken_end=0.80,
            trigger_char_start=0,
            trigger_char_end=18,
            confidence=1.0,
            source="final_package_semantic_binding",
            policy="EXPLICIT",
            semantic_group_id="g",
            sequence_order=3,
            group_animation_policy="SEQUENTIAL_WITHIN_PHRASE",
        ),
    ]
    scheduled = schedule_windows(raw, beat, 2.0, {"later"})
    beat = beat.model_copy(update={"asset_activations": scheduled})
    composition = [
        CompositionBeat(
            beat_id=beat.id,
            items=[
                LayoutItem(asset_id="later", x=0.50, y=0.50, width=0.30, height=0.35),
                LayoutItem(asset_id="early-a", x=0.25, y=0.50, width=0.22, height=0.25),
                LayoutItem(asset_id="early-b", x=0.75, y=0.50, width=0.22, height=0.25),
            ],
        )
    ]

    motion = MotionPlanner().plan([beat], composition)
    by_asset = {cue.asset_id: cue for cue in motion}
    assert by_asset["early-a"].start < by_asset["early-b"].start
    assert by_asset["early-a"].start < by_asset["later"].start
    assert by_asset["early-b"].start < by_asset["later"].start

    report = StorySyncQA().inspect(story=[beat], motion=motion)

    assert report.passed, report.violations
    assert not any(
        "sequence_order_motion_reversed" in row
        or "sequence_order_motion_collapsed" in row
        for row in report.violations
    )

