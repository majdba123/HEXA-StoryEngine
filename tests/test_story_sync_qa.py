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


def test_story_sync_qa_reports_settle_past_next_semantic_handoff() -> None:
    beat = _beat(
        AssetActivation(
            asset_id="a",
            spoken_start=0.30,
            spoken_end=1.20,
            trigger_char_start=0,
            trigger_char_end=4,
            confidence=1.0,
            source="final_package_semantic_binding",
            policy="EXPLICIT",
            visual_focus="PRIMARY",
        ),
        AssetActivation(
            asset_id="b",
            spoken_start=0.48,
            spoken_end=1.40,
            trigger_char_start=5,
            trigger_char_end=9,
            confidence=1.0,
            source="final_package_semantic_binding",
            policy="EXPLICIT",
            visual_focus="RESULT",
        ),
    )
    beat = beat.model_copy(update={
        "asset_activations": schedule_windows(
            beat.asset_activations, beat, beat.end, {"a"}
        ),
    })
    composition = [CompositionBeat(
        beat_id=beat.id,
        items=[
            LayoutItem(asset_id="a", x=0.3, y=0.5, width=0.2, height=0.2),
            LayoutItem(asset_id="b", x=0.7, y=0.5, width=0.2, height=0.2),
        ],
    )]
    motion = MotionPlanner().plan([beat], composition)
    corrupted = []
    for cue in motion:
        if cue.asset_id == "a":
            corrupted.append(cue.model_copy(update={
                "params": {**cue.params, "semantic_settle_time": 0.70},
            }))
        else:
            corrupted.append(cue)

    report = StorySyncQA().inspect(story=[beat], motion=corrupted)

    assert any("settle_past_next_handoff" in row for row in report.violations)


def test_story_sync_qa_allows_same_frame_aware_semantic_cohort_overlap() -> None:
    beat = _beat(
        AssetActivation(
            asset_id="a", spoken_start=0.40, spoken_end=1.20,
            confidence=1.0, source="final_package_semantic_binding",
            policy="EXPLICIT", visual_focus="PRIMARY",
        ),
        AssetActivation(
            asset_id="b", spoken_start=0.45, spoken_end=1.20,
            confidence=1.0, source="final_package_semantic_binding",
            policy="EXPLICIT", visual_focus="RESULT",
        ),
    )
    beat = beat.model_copy(update={
        "asset_activations": schedule_windows(
            beat.asset_activations, beat, beat.end, {"a"}
        ),
    })
    composition = [CompositionBeat(
        beat_id=beat.id,
        items=[
            LayoutItem(asset_id="a", x=0.3, y=0.5, width=0.2, height=0.2),
            LayoutItem(asset_id="b", x=0.7, y=0.5, width=0.2, height=0.2),
        ],
    )]
    motion = MotionPlanner().plan([beat], composition)

    report = StorySyncQA().inspect(story=[beat], motion=motion)

    assert not any(
        "settle_past_next_handoff" in row or "strong_focus_overlap" in row
        for row in report.violations
    ), report.violations


def _v2_attention_peak_case(peak_progress: float) -> tuple[StoryBeat, MotionCue]:
    beat = _beat(AssetActivation(
        asset_id="a",
        spoken_start=0.40,
        spoken_end=1.40,
        confidence=1.0,
        source="final_package_semantic_binding",
        policy="EXPLICIT",
        visual_focus="PRIMARY",
    ))
    scheduled = schedule_windows(beat.asset_activations, beat, beat.end, {"a"})
    beat = beat.model_copy(update={"asset_activations": scheduled})
    window = scheduled[0]
    duration = window.settle_at - window.reveal_start
    cue = MotionCue(
        beat_id=beat.id,
        asset_id="a",
        kind="program_v3",
        start=window.reveal_start,
        end=window.settle_at,
        params={
            "semantic_settle_time": window.settle_at,
            "semantic_focus": {
                "active": True,
                "role": "PRIMARY",
                "semantic_role": "PRIMARY",
                "strength": 0.9,
            },
            "program": {
                "name": "peak-qa",
                "settle_progress": 1.0,
                "keyframes": [
                    {"progress": 0.0, "dx": 0.0, "dy": 0.0, "scale": 1.0, "easing": "linear"},
                    {"progress": peak_progress, "dx": 0.0, "dy": 0.0, "scale": 1.08, "easing": "linear"},
                    {"progress": 1.0, "dx": 0.0, "dy": 0.0, "scale": 1.0, "easing": "linear"},
                ],
            },
        },
    )
    assert duration > 0
    return beat, cue


def test_story_sync_qa_accepts_frame_aware_semantic_focus_peak() -> None:
    beat, cue = _v2_attention_peak_case(0.55)

    report = StorySyncQA().inspect(story=[beat], motion=[cue])

    assert report.passed, report.violations
    assert report.entries[0].actual_peak == pytest.approx(
        report.entries[0].semantic_peak,
        abs=0.02,
    )


def test_story_sync_qa_rejects_semantic_focus_peak_too_early() -> None:
    beat, cue = _v2_attention_peak_case(0.05)

    report = StorySyncQA().inspect(story=[beat], motion=[cue])

    assert any("focus_peak_too_early" in row for row in report.violations)


def test_story_sync_qa_rejects_semantic_focus_peak_too_late() -> None:
    beat, cue = _v2_attention_peak_case(0.98)

    report = StorySyncQA().inspect(story=[beat], motion=[cue])

    assert any("focus_peak_too_late" in row for row in report.violations)

