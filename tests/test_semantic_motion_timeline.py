from __future__ import annotations

import pytest

from app.choreography import (
    ChoreographyDirective,
    ChoreographyPattern,
    ChoreographyPlan,
    EventFlowStage,
    EventFlowStep,
    HookKind,
    SemanticEventFlow,
    SequencePhase,
)
from app.models import (
    CompositionBeat,
    LayoutItem,
    StoryBeat,
    StoryRelation,
    StorySemanticContext,
    Transcript,
    TranscriptWord,
)
from app.motion import MotionPlanner
from app.qa import MotionInteractionQA
from app.story.planner import StoryPlanner
from app.story.windows import StoryAssetActivation


def test_relation_script_span_resolves_to_spoken_window() -> None:
    transcript = Transcript(
        duration=4.0,
        segments=[],
        words=[
            TranscriptWord(start=1.00, end=1.18, text="A", char_start=0, char_end=1),
            TranscriptWord(start=2.00, end=2.28, text="attacks", char_start=2, char_end=9),
            TranscriptWord(start=2.30, end=2.55, text="B", char_start=10, char_end=11),
        ],
    )
    context = StorySemanticContext(relations=[
        StoryRelation(
            source_unit_id="A",
            target_unit_id="B",
            kind="ATTACKS",
            authority="FINAL_PACKAGE_ASSET_RELATION",
            trigger_text="attacks",
            trigger_char_start=2,
            trigger_char_end=9,
        )
    ])
    resolved = StoryPlanner._resolve_relation_timing(
        context, transcript=transcript, script="A attacks B",
        beat_start=0.8, beat_end=3.0,
    )
    relation = resolved.relations[0]
    assert relation.spoken_start == pytest.approx(2.00)
    assert relation.spoken_end == pytest.approx(2.28)


def _activation(asset_id: str, *, spoken_start: float, spoken_end: float, roles: list[str]):
    return StoryAssetActivation(
        asset_id=asset_id,
        semantic_unit_id=asset_id,
        trigger_text=asset_id,
        trigger_char_start=0,
        trigger_char_end=1,
        spoken_start=spoken_start,
        spoken_end=spoken_end,
        confidence=0.99,
        source="final_package_semantic_binding",
        policy="EXPLICIT",
        semantic_event_id="E1",
        semantic_event_order=1,
        semantic_event_roles=roles,
        phrase_start=spoken_start,
        phrase_end=spoken_end,
        reveal_start=spoken_start,
        semantic_peak=spoken_start + (spoken_end - spoken_start) * 0.5,
        settle_at=spoken_end,
        activation_policy="OWN_WINDOW",
    )


def _fixture():
    a = _activation("a", spoken_start=1.0, spoken_end=1.3, roles=["LEADER"])
    b = _activation("b", spoken_start=2.0, spoken_end=2.3, roles=["PARTICIPANT"])
    c = _activation("c", spoken_start=2.6, spoken_end=2.9, roles=["RESULT"])
    beat = StoryBeat(
        id="beat", scene_id="scene", start=0.0, end=3.2,
        audio_start=0.0, audio_end=3.0, narration="A then B relation then C",
        primary_asset_ids=["a"], support_asset_ids=["b", "c"],
        action="REVEAL_DETAIL", asset_activations=[a, b, c],
    )
    composition = CompositionBeat(beat_id=beat.id, items=[
        LayoutItem(asset_id="a", x=0.22, y=0.50, width=0.18, height=0.22),
        LayoutItem(asset_id="b", x=0.50, y=0.50, width=0.18, height=0.22),
        LayoutItem(asset_id="c", x=0.80, y=0.50, width=0.18, height=0.22),
    ])
    common = dict(
        participant_asset_ids=("a", "b", "c"),
        source_asset_id="a", target_asset_id="b", result_asset_id="c",
        relationship="ATTACKS", semantic_action="CONNECT",
        authority="FINAL_PACKAGE_ASSET_RELATION",
        trigger_char_start=10, trigger_char_end=20,
        spoken_start=2.0, spoken_end=2.7,
    )
    flow = SemanticEventFlow(
        event_id="E1", order=1,
        leader_asset_ids=("a",), participant_asset_ids=("b",), result_asset_ids=("c",),
        stages=(
            EventFlowStage.ESTABLISH, EventFlowStage.ADD, EventFlowStage.INTERACT,
            EventFlowStage.REACT, EventFlowStage.PAYOFF, EventFlowStage.RELEASE,
        ),
        steps=(
            EventFlowStep(EventFlowStage.ESTABLISH, focus_asset_id="a", participant_asset_ids=("a",)),
            EventFlowStep(EventFlowStage.ADD, focus_asset_id="b", participant_asset_ids=("b",)),
            EventFlowStep(EventFlowStage.INTERACT, focus_asset_id="a", **common),
            EventFlowStep(EventFlowStage.REACT, focus_asset_id="b", **common),
            EventFlowStep(EventFlowStage.PAYOFF, focus_asset_id="c", **common),
            EventFlowStep(EventFlowStage.RELEASE, focus_asset_id="c", participant_asset_ids=("c",)),
        ),
    )
    directive = ChoreographyDirective(
        beat_id=beat.id, sequence_id="sequence-001", phase=SequencePhase.ACTION,
        action="CONNECT", pattern=ChoreographyPattern.CAUSE_EFFECT_CHAIN,
        hook=HookKind.OPEN, energy=0.82, primary_asset_id="a", event_flows=(flow,),
    )
    return beat, composition, ChoreographyPlan(directives=(directive,))


def test_motion_timeline_reactivates_relation_with_overlap_and_payoff() -> None:
    beat, composition, choreography = _fixture()
    cues = MotionPlanner().plan([beat], [composition], choreography)
    by_id = {cue.asset_id: cue for cue in cues}
    a = {row.phase: row for row in by_id["a"].segments}
    b = {row.phase: row for row in by_id["b"].segments}
    c = {row.phase: row for row in by_id["c"].segments}

    assert {"ENTRY", "INTERACT"} <= set(a)
    assert {"ENTRY", "REACT"} <= set(b)
    assert {"ENTRY", "PAYOFF"} <= set(c)
    assert a["ENTRY"].start == pytest.approx(by_id["a"].start)
    assert a["INTERACT"].start == pytest.approx(2.0)
    assert b["REACT"].start > a["INTERACT"].start
    assert min(a["INTERACT"].end, b["REACT"].end) > max(a["INTERACT"].start, b["REACT"].start)
    assert c["PAYOFF"].start >= 2.6

    for cue in cues:
        for segment in cue.segments:
            final = segment.program["keyframes"][-1]
            assert final["dx"] == pytest.approx(0.0)
            assert final["dy"] == pytest.approx(0.0)
            assert final["scale"] == pytest.approx(1.0)

    report = MotionInteractionQA().inspect(story=[beat], motion=cues)
    assert report.ok, report.violations
    assert report.checked_relations == 1


def test_motion_interaction_qa_rejects_non_overlapping_relation() -> None:
    beat, composition, choreography = _fixture()
    cues = MotionPlanner().plan([beat], [composition], choreography)
    cue = next(row for row in cues if row.asset_id == "b")
    index = next(i for i, row in enumerate(cue.segments) if row.phase == "REACT")
    bad = cue.segments[index].model_copy(update={"start": 2.55, "end": 2.69})
    segments = list(cue.segments)
    segments[index] = bad
    broken_cue = cue.model_copy(update={"segments": segments})
    report = MotionInteractionQA().inspect(
        story=[beat],
        motion=[broken_cue if row.asset_id == "b" else row for row in cues],
    )
    assert not report.ok
    assert any(row.code == "NO_RELATION_OVERLAP" for row in report.violations)


def test_motion_interaction_qa_rejects_geometry_drift() -> None:
    beat, composition, choreography = _fixture()
    cues = MotionPlanner().plan([beat], [composition], choreography)
    cue = next(row for row in cues if row.asset_id == "a")
    index = next(i for i, row in enumerate(cue.segments) if row.phase == "INTERACT")
    segment = cue.segments[index]
    program = dict(segment.program)
    keyframes = [dict(row) for row in program["keyframes"]]
    keyframes[-1]["dx"] = 0.01
    program["keyframes"] = keyframes
    bad_segment = segment.model_copy(update={"program": program})
    segments = list(cue.segments)
    segments[index] = bad_segment
    broken_cue = cue.model_copy(update={"segments": segments})
    report = MotionInteractionQA().inspect(
        story=[beat],
        motion=[broken_cue if row.asset_id == "a" else row for row in cues],
    )
    assert not report.ok
    assert any(row.code == "SEGMENT_GEOMETRY_DRIFT" for row in report.violations)
