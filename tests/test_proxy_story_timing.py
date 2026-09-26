from __future__ import annotations

import pytest

from app.choreography import (
    ChoreographyDirective,
    ChoreographyPattern,
    ChoreographyPlan,
    HookKind,
    SequencePhase,
)
from app.choreography.event_flow import SemanticEventFlowPlanner
from app.models import CompositionBeat, LayoutItem, SemanticEventProxy, StoryBeat
from app.motion import MotionPlanner
from app.story.sync_qa import StorySyncQA
from app.story.windows import StoryAssetActivation


def _story_activation() -> StoryAssetActivation:
    return StoryAssetActivation(
        asset_id="carrier",
        semantic_unit_id="owner-unit",
        trigger_text="owner",
        trigger_char_start=0,
        trigger_char_end=5,
        spoken_start=0.10,
        spoken_end=0.80,
        confidence=1.0,
        source="final_package_semantic_binding",
        policy="EXPLICIT",
        semantic_event_id="E1",
        semantic_event_order=1,
        semantic_event_roles=["LEADER"],
        phrase_start=0.10,
        phrase_end=0.80,
        reveal_start=0.10,
        semantic_peak=0.35,
        settle_at=0.70,
        activation_policy="OWN_WINDOW",
    ).with_legacy_evidence()


def _proxy(
    event_id: str,
    order: int,
    *,
    reveal: float,
    peak: float,
    settle: float,
    role: str,
    dependency_ids: list[str],
) -> SemanticEventProxy:
    return SemanticEventProxy(
        asset_id="carrier",
        semantic_unit_id=f"{event_id}-unit",
        semantic_parent_id="owner-unit",
        semantic_group_id="group-1",
        semantic_event_id=event_id,
        semantic_event_order=order,
        semantic_event_roles=[role],
        semantic_event_dependency_ids=dependency_ids,
        trigger_text=event_id,
        trigger_char_start=order * 10,
        trigger_char_end=order * 10 + 4,
        spoken_start=reveal,
        spoken_end=settle,
        reveal_start=reveal,
        semantic_peak=peak,
        settle_at=settle,
        confidence=1.0,
        authority="FINAL_PACKAGE_GROUP_PROXY",
        visual_focus="PRIMARY",
        evidence=["test"],
    )


def _fixture() -> tuple[StoryBeat, CompositionBeat, ChoreographyPlan]:
    p2 = _proxy(
        "E2", 2,
        reveal=1.00,
        peak=1.30,  # Intentionally not GOLDEN_MAJOR within [1.0, 1.6].
        settle=1.60,
        role="LEADER",
        dependency_ids=["E1"],
    )
    p3 = _proxy(
        "E3", 3,
        reveal=1.70,
        peak=2.00,  # Also deliberately non-golden.
        settle=2.30,
        role="PARTICIPANT",
        dependency_ids=["E2"],
    )
    beat = StoryBeat(
        id="beat",
        scene_id="scene",
        start=0.0,
        end=2.6,
        audio_start=0.0,
        audio_end=2.5,
        narration="owner then proxy two then proxy three",
        primary_asset_ids=["carrier"],
        support_asset_ids=[],
        action="EXPLAIN",
        asset_activations=[_story_activation()],
        semantic_event_proxies=[p2, p3],
    )
    composition = CompositionBeat(
        beat_id="beat",
        items=[LayoutItem(asset_id="carrier", x=0.5, y=0.5, width=0.28, height=0.32)],
    )
    event_flows = SemanticEventFlowPlanner().compile(
        beat=beat,
        interactions=(),
        transitions=(),
    )
    choreography = ChoreographyPlan(directives=(ChoreographyDirective(
        beat_id="beat",
        sequence_id="sequence",
        phase=SequencePhase.ACTION,
        action="EXPLAIN",
        pattern=ChoreographyPattern.PROGRESSIVE_BUILD,
        hook=HookKind.NONE,
        energy=0.6,
        primary_asset_id="carrier",
        event_flows=event_flows,
    ),))
    return beat, composition, choreography


def test_same_carrier_keeps_one_semantic_segment_per_authored_proxy_event() -> None:
    beat, composition, choreography = _fixture()
    cue = MotionPlanner().plan([beat], [composition], choreography)[0]

    proxy_segments = [
        segment for segment in cue.segments
        if segment.semantic_event_id in {"E2", "E3"}
        and segment.phase in {"ESTABLISH", "ADD", "PAYOFF"}
    ]

    assert [segment.semantic_event_id for segment in proxy_segments] == ["E2", "E3"]


def test_proxy_motion_uses_exact_story_semantic_peak_not_recomputed_peak() -> None:
    beat, composition, choreography = _fixture()
    motion = MotionPlanner().plan([beat], [composition], choreography)

    report = StorySyncQA().inspect(story=[beat], motion=motion)

    assert report.passed, report.violations
    entries = {
        entry.semantic_unit_id: entry
        for entry in report.entries
        if entry.activation_policy == "COMPOUND_PROXY"
    }
    assert entries["E2-unit"].actual_peak == pytest.approx(1.30, abs=1 / 30)
    assert entries["E3-unit"].actual_peak == pytest.approx(2.00, abs=1 / 30)



def test_proxy_events_before_carrier_owner_activation_keep_independent_segments() -> None:
    owner = StoryAssetActivation(
        asset_id="carrier",
        semantic_unit_id="owner-unit",
        trigger_text="owner",
        trigger_char_start=20,
        trigger_char_end=25,
        spoken_start=1.40,
        spoken_end=1.80,
        confidence=1.0,
        source="final_package_semantic_binding",
        policy="EXPLICIT",
        semantic_event_id="E3",
        semantic_event_order=3,
        semantic_event_roles=["LEADER"],
        phrase_start=1.40,
        phrase_end=1.80,
        reveal_start=1.40,
        semantic_peak=1.60,
        settle_at=1.75,
        activation_policy="OWN_WINDOW",
    ).with_legacy_evidence()
    p1 = _proxy(
        "E1", 1, reveal=0.25, peak=0.55, settle=0.75,
        role="LEADER", dependency_ids=[],
    )
    p2 = _proxy(
        "E2", 2, reveal=0.85, peak=1.05, settle=1.25,
        role="LEADER", dependency_ids=["E1"],
    )
    beat = StoryBeat(
        id="beat-preowner",
        scene_id="scene-preowner",
        start=0.0,
        end=2.0,
        audio_start=0.0,
        audio_end=2.0,
        narration="proxy one proxy two owner",
        primary_asset_ids=["carrier"],
        support_asset_ids=[],
        action="EXPLAIN",
        asset_activations=[owner],
        semantic_event_proxies=[p1, p2],
    )
    composition = CompositionBeat(
        beat_id=beat.id,
        items=[
            LayoutItem(
                asset_id="carrier",
                x=0.5,
                y=0.5,
                width=0.28,
                height=0.32,
            )
        ],
    )
    event_flows = SemanticEventFlowPlanner().compile(
        beat=beat,
        interactions=(),
        transitions=(),
    )
    choreography = ChoreographyPlan(directives=(ChoreographyDirective(
        beat_id=beat.id,
        sequence_id="preowner-sequence",
        phase=SequencePhase.ACTION,
        action="EXPLAIN",
        pattern=ChoreographyPattern.PROGRESSIVE_BUILD,
        hook=HookKind.NONE,
        energy=0.6,
        primary_asset_id="carrier",
        event_flows=event_flows,
    ),))

    motion = MotionPlanner().plan([beat], [composition], choreography)
    cue = motion[0]
    proxy_segments = [
        segment
        for segment in cue.segments
        if segment.semantic_event_id in {"E1", "E2"}
        and segment.phase in {"ESTABLISH", "ADD", "PAYOFF"}
    ]

    assert [segment.semantic_event_id for segment in proxy_segments] == ["E1", "E2"]
    assert not [segment for segment in cue.segments if segment.phase == "ENTRY"]
    report = StorySyncQA().inspect(story=[beat], motion=motion)
    assert report.passed, report.violations
