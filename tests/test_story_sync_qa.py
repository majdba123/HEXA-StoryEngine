from __future__ import annotations

import pytest

from app.models import AssetActivation, MotionCue, StoryBeat
from app.story.sync_qa import StorySyncQA


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
