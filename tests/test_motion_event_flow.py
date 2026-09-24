from __future__ import annotations

from dataclasses import replace

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
from app.models import CompositionBeat, LayoutItem, StoryBeat
from app.motion import MotionPlanner
from app.story.windows import StoryAssetActivation


def _activation(
    asset_id: str,
    *,
    start: float,
    peak: float,
    settle: float,
    end: float,
    event_id: str,
    event_order: int,
    roles: list[str],
) -> StoryAssetActivation:
    return StoryAssetActivation(
        asset_id=asset_id,
        semantic_unit_id=asset_id,
        trigger_text=asset_id,
        trigger_char_start=event_order * 10,
        trigger_char_end=event_order * 10 + 5,
        spoken_start=start,
        spoken_end=end,
        confidence=0.99,
        source="final_package_semantic_binding",
        policy="EXPLICIT",
        binding_type="EXPLICIT",
        semantic_event_id=event_id,
        semantic_event_order=event_order,
        semantic_event_roles=roles,
        phrase_start=start,
        phrase_end=end,
        reveal_start=start,
        semantic_peak=peak,
        settle_at=settle,
        activation_policy="OWN_WINDOW",
    ).with_legacy_evidence()


def _fixture() -> tuple[StoryBeat, CompositionBeat, ChoreographyPlan]:
    a = _activation(
        "a", start=0.10, peak=0.22, settle=0.34, end=0.38,
        event_id="E1", event_order=1, roles=["LEADER"],
    )
    b = _activation(
        "b", start=0.40, peak=0.53, settle=0.66, end=0.70,
        event_id="E1", event_order=1, roles=["PARTICIPANT"],
    )
    c = _activation(
        "c", start=0.78, peak=0.92, settle=1.06, end=1.10,
        event_id="E2", event_order=2, roles=["LEADER", "RESULT"],
    )
    context = _activation(
        "context", start=0.10, peak=0.20, settle=0.32, end=0.38,
        event_id="E1", event_order=1, roles=["CONTEXT"],
    )
    beat = StoryBeat(
        id="beat",
        scene_id="scene",
        start=0.0,
        end=1.3,
        audio_start=0.0,
        audio_end=1.2,
        narration="a b c",
        primary_asset_ids=["a"],
        support_asset_ids=["b", "c", "context"],
        action="EXPLAIN",
        asset_activations=[a, b, c, context],
    )
    composition = CompositionBeat(
        beat_id=beat.id,
        items=[
            LayoutItem(asset_id="a", x=0.20, y=0.50, width=0.16, height=0.20),
            LayoutItem(asset_id="b", x=0.50, y=0.50, width=0.16, height=0.20),
            LayoutItem(asset_id="c", x=0.80, y=0.50, width=0.16, height=0.20),
            LayoutItem(asset_id="context", x=0.50, y=0.78, width=0.14, height=0.16),
        ],
    )
    e1 = SemanticEventFlow(
        event_id="E1",
        order=1,
        leader_asset_ids=("a",),
        participant_asset_ids=("b",),
        context_asset_ids=("context",),
        stages=(
            EventFlowStage.ESTABLISH,
            EventFlowStage.ADD,
            EventFlowStage.INTERACT,
            EventFlowStage.REACT,
            EventFlowStage.RELEASE,
        ),
        steps=(
            EventFlowStep(EventFlowStage.ESTABLISH, focus_asset_id="a", participant_asset_ids=("a",)),
            EventFlowStep(EventFlowStage.ADD, focus_asset_id="b", participant_asset_ids=("b",)),
            EventFlowStep(
                EventFlowStage.INTERACT,
                focus_asset_id="a",
                participant_asset_ids=("a", "b"),
                source_asset_id="a",
                target_asset_id="b",
                relationship="CAUSES",
                semantic_action="CONNECT",
                authority="FINAL_PACKAGE_ASSET_RELATION",
            ),
            EventFlowStep(
                EventFlowStage.REACT,
                focus_asset_id="b",
                participant_asset_ids=("a", "b"),
                source_asset_id="a",
                target_asset_id="b",
                relationship="CAUSES",
                semantic_action="CONNECT",
                authority="FINAL_PACKAGE_ASSET_RELATION",
            ),
            EventFlowStep(EventFlowStage.RELEASE, focus_asset_id="c", participant_asset_ids=("c",)),
        ),
        handoff_to_event_id="E2",
        handoff_to_asset_id="c",
    )
    e2 = SemanticEventFlow(
        event_id="E2",
        order=2,
        dependency_ids=("E1",),
        leader_asset_ids=("c",),
        result_asset_ids=("c",),
        stages=(EventFlowStage.ESTABLISH, EventFlowStage.PAYOFF, EventFlowStage.RELEASE),
        steps=(
            EventFlowStep(EventFlowStage.ESTABLISH, focus_asset_id="c", participant_asset_ids=("c",)),
            EventFlowStep(
                EventFlowStage.PAYOFF,
                focus_asset_id="c",
                participant_asset_ids=("c",),
                result_asset_id="c",
            ),
            EventFlowStep(EventFlowStage.RELEASE, focus_asset_id="c", participant_asset_ids=("c",)),
        ),
    )
    directive = ChoreographyDirective(
        beat_id=beat.id,
        sequence_id="sequence-001",
        phase=SequencePhase.ACTION,
        action="CONNECT",
        pattern=ChoreographyPattern.CAUSE_EFFECT_CHAIN,
        hook=HookKind.OPEN,
        energy=0.8,
        primary_asset_id="a",
        event_flows=(e1, e2),
    )
    return beat, composition, ChoreographyPlan(directives=(directive,))


def test_motion_executes_choreography_event_steps_not_just_pattern_metadata() -> None:
    beat, composition, choreography = _fixture()
    cues = MotionPlanner().plan([beat], [composition], choreography)
    by_id = {cue.asset_id: cue for cue in cues}

    assert by_id["a"].params["semantic_focus"]["event_flow"]["stage"] == "INTERACT"
    assert by_id["b"].params["semantic_focus"]["event_flow"]["stage"] == "REACT"
    assert by_id["c"].params["semantic_focus"]["event_flow"]["stage"] == "PAYOFF"
    assert by_id["context"].params["semantic_focus"]["event_flow"] is None

    assert "event_chain_establish_interact_" in by_id["a"].params["program"]["name"]
    assert "event_chain_add_react_" in by_id["b"].params["program"]["name"]
    assert "event_chain_establish_payoff_" in by_id["c"].params["program"]["name"]
    assert [
        phase["stage"]
        for phase in by_id["a"].params["semantic_focus"]["event_flow"]["phase_chain"]
    ] == ["ESTABLISH", "INTERACT"]

    # Story remains timing authority.
    assert by_id["a"].start == pytest.approx(0.10)
    assert by_id["b"].start == pytest.approx(0.40)
    assert by_id["c"].start == pytest.approx(0.78)

    # CONNECT keeps the source/target relationship directional: source moves toward
    # target and the target acknowledges by moving back toward the source.
    a_frames = by_id["a"].params["program"]["keyframes"]
    b_frames = by_id["b"].params["program"]["keyframes"]
    assert any(frame["dx"] > 0.0 for frame in a_frames[1:-1])
    assert any(frame["dx"] < 0.0 for frame in b_frames[1:-1])
    max_scale = {
        asset_id: max(frame["scale"] for frame in cue.params["program"]["keyframes"])
        for asset_id, cue in by_id.items()
    }
    assert max_scale["c"] > max_scale["b"] > max_scale["context"]

    # Final authored Composition geometry is still absolute.
    for cue in cues:
        final = cue.params["program"]["keyframes"][-1]
        assert final["dx"] == pytest.approx(0.0)
        assert final["dy"] == pytest.approx(0.0)
        assert final["scale"] == pytest.approx(1.0)


def test_event_flow_changes_motion_program_without_changing_story_timing() -> None:
    beat, composition, choreography = _fixture()
    with_flow = {cue.asset_id: cue for cue in MotionPlanner().plan([beat], [composition], choreography)}

    directive = choreography.directives[0]
    without_flow = ChoreographyPlan(directives=(replace(directive, event_flows=()),))
    baseline = {
        cue.asset_id: cue
        for cue in MotionPlanner().plan([beat], [composition], without_flow)
    }

    for asset_id in ("a", "b", "c", "context"):
        assert with_flow[asset_id].start == pytest.approx(baseline[asset_id].start)
        assert with_flow[asset_id].end == pytest.approx(baseline[asset_id].end)

    assert with_flow["a"].params["program"] != baseline["a"].params["program"]
    assert with_flow["b"].params["program"] != baseline["b"].params["program"]
    assert with_flow["c"].params["program"] != baseline["c"].params["program"]
    assert with_flow["context"].params["program"] == baseline["context"].params["program"]


def test_short_story_window_collapses_event_chain_to_dominant_phase() -> None:
    beat, composition, choreography = _fixture()
    short_a = beat.asset_activations[0].model_copy(update={
        "semantic_peak": 0.14,
        "settle_at": 0.18,
        "spoken_end": 0.19,
        "phrase_end": 0.19,
    })
    beat = beat.model_copy(update={
        "asset_activations": [short_a, *beat.asset_activations[1:]],
    })

    cues = MotionPlanner().plan([beat], [composition], choreography)
    a = next(cue for cue in cues if cue.asset_id == "a")

    assert "event_chain_interact_" in a.params["program"]["name"]
    assert "event_chain_establish_interact_" not in a.params["program"]["name"]
    assert a.start == pytest.approx(0.10)
    assert a.params["semantic_settle_time"] == pytest.approx(0.18)


def test_event_flow_phase_chain_keeps_context_quiet_and_final_geometry_exact() -> None:
    beat, composition, choreography = _fixture()
    cues = MotionPlanner().plan([beat], [composition], choreography)
    by_id = {cue.asset_id: cue for cue in cues}

    assert by_id["context"].params["semantic_focus"]["event_flow"] is None
    assert not by_id["context"].params["program"]["name"].startswith("event_chain_")
    for cue in cues:
        settle = cue.params["program"]["settle_progress"]
        for frame in cue.params["program"]["keyframes"]:
            if frame["progress"] >= settle - 1e-9:
                assert frame["dx"] == pytest.approx(0.0)
                assert frame["dy"] == pytest.approx(0.0)
                assert frame["scale"] == pytest.approx(1.0)


def test_story_event_id_overrides_stronger_stage_from_other_event_for_reused_asset() -> None:
    activation = _activation(
        "shared", start=0.60, peak=0.72, settle=0.86, end=0.90,
        event_id="E2", event_order=2, roles=["LEADER"],
    )
    beat = StoryBeat(
        id="reuse-beat",
        scene_id="scene",
        start=0.0,
        end=1.0,
        audio_start=0.0,
        audio_end=0.95,
        narration="reuse",
        primary_asset_ids=["shared"],
        action="EXPLAIN",
        asset_activations=[activation],
    )
    composition = CompositionBeat(
        beat_id=beat.id,
        items=[LayoutItem(asset_id="shared", x=0.6, y=0.5, width=0.2, height=0.2)],
    )
    e1 = SemanticEventFlow(
        event_id="E1",
        order=1,
        steps=(
            EventFlowStep(
                EventFlowStage.REACT,
                focus_asset_id="shared",
                participant_asset_ids=("shared",),
                source_asset_id="actor",
                target_asset_id="shared",
                authority="FINAL_PACKAGE_ASSET_RELATION",
            ),
            EventFlowStep(EventFlowStage.RELEASE, focus_asset_id="shared"),
        ),
        stages=(EventFlowStage.REACT, EventFlowStage.RELEASE),
    )
    e2 = SemanticEventFlow(
        event_id="E2",
        order=2,
        leader_asset_ids=("shared",),
        steps=(
            EventFlowStep(
                EventFlowStage.ESTABLISH,
                focus_asset_id="shared",
                participant_asset_ids=("shared",),
            ),
            EventFlowStep(EventFlowStage.RELEASE, focus_asset_id="shared"),
        ),
        stages=(EventFlowStage.ESTABLISH, EventFlowStage.RELEASE),
    )
    directive = ChoreographyDirective(
        beat_id=beat.id,
        sequence_id="sequence-001",
        phase=SequencePhase.ACTION,
        action="EXPLAIN",
        pattern=ChoreographyPattern.PROGRESSIVE_BUILD,
        hook=HookKind.OPEN,
        primary_asset_id="shared",
        event_flows=(e1, e2),
    )
    choreography = ChoreographyPlan(directives=(directive,))

    cue = MotionPlanner().plan([beat], [composition], choreography)[0]
    event_flow = cue.params["semantic_focus"]["event_flow"]

    assert event_flow["event_id"] == "E2"
    assert event_flow["stage"] == "ESTABLISH"
    assert "event_chain_establish_" in cue.params["program"]["name"]
    assert "react" not in cue.params["program"]["name"]


def test_relation_flavors_survive_event_flow_instead_of_becoming_generic_interaction() -> None:
    from app.motion.event_flow import MotionEventPhase

    compare_source = MotionEventPhase(
        event_id="E", event_order=1, stage=EventFlowStage.INTERACT,
        step_index=0, involvement="SOURCE", focus_asset_id="a",
        source_asset_id="a", target_asset_id="b", result_asset_id=None,
        relationship="PARALLEL_CAUSES", semantic_action="COMPARE",
        authority="FINAL_PACKAGE_ASSET_RELATION",
    )
    connect_source = replace(compare_source, semantic_action="CONNECT", relationship="ENABLES")
    loop_source = replace(compare_source, semantic_action="LOOP", relationship="PERSISTS_OVER_TIME")

    compare = MotionPlanner._phase_transform(
        phase=compare_source, vector=(0.4, 0.0), focus_strength=1.0
    )
    connect = MotionPlanner._phase_transform(
        phase=connect_source, vector=(0.4, 0.0), focus_strength=1.0
    )
    loop = MotionPlanner._phase_transform(
        phase=loop_source, vector=(0.4, 0.0), focus_strength=1.0
    )

    assert compare[0] < 0.0
    assert connect[0] > 0.0
    assert abs(loop[0]) < 1e-9 and loop[1] > 0.0
    assert len({compare, connect, loop}) == 3


def test_multiple_results_are_all_payoff_visuals_not_quiet_support() -> None:
    r1 = _activation(
        "r1", start=0.45, peak=0.58, settle=0.72, end=0.76,
        event_id="E1", event_order=1, roles=["RESULT"],
    )
    r2 = _activation(
        "r2", start=0.45, peak=0.58, settle=0.72, end=0.76,
        event_id="E1", event_order=1, roles=["RESULT"],
    )
    beat = StoryBeat(
        id="multi-result", scene_id="scene", start=0.0, end=1.0,
        audio_start=0.0, audio_end=0.9, narration="two results",
        primary_asset_ids=["r1"], support_asset_ids=["r2"], action="RESULT",
        asset_activations=[r1, r2],
    )
    composition = CompositionBeat(
        beat_id=beat.id,
        items=[
            LayoutItem(asset_id="r1", x=0.35, y=0.5, width=0.2, height=0.2),
            LayoutItem(asset_id="r2", x=0.65, y=0.5, width=0.2, height=0.2),
        ],
    )
    flow = SemanticEventFlow(
        event_id="E1", order=1, result_asset_ids=("r1", "r2"),
        stages=(EventFlowStage.PAYOFF, EventFlowStage.RELEASE),
        steps=(
            EventFlowStep(EventFlowStage.PAYOFF, focus_asset_id="r1", participant_asset_ids=("r1",), result_asset_id="r1"),
            EventFlowStep(EventFlowStage.PAYOFF, focus_asset_id="r2", participant_asset_ids=("r2",), result_asset_id="r2"),
            EventFlowStep(EventFlowStage.RELEASE, focus_asset_id="r2", participant_asset_ids=("r2",)),
        ),
    )
    directive = ChoreographyDirective(
        beat_id=beat.id, sequence_id="sequence-001", phase=SequencePhase.CONSEQUENCE,
        action="RESULT", pattern=ChoreographyPattern.FOCUS_TRANSFER,
        hook=HookKind.OPEN, primary_asset_id="r1", event_flows=(flow,),
    )
    cues = MotionPlanner().plan(
        [beat], [composition], ChoreographyPlan(directives=(directive,))
    )
    by_id = {cue.asset_id: cue for cue in cues}

    assert by_id["r1"].params["semantic_focus"]["event_flow"]["stage"] == "PAYOFF"
    assert by_id["r2"].params["semantic_focus"]["event_flow"]["stage"] == "PAYOFF"
    assert by_id["r2"].params["semantic_focus"]["cohort_role"] == "result_peer"
    assert by_id["r2"].params["semantic_focus"]["cohort_gain"] >= 0.8
    assert max(f["scale"] for f in by_id["r2"].params["program"]["keyframes"]) > 1.04


def test_compound_required_multi_cutout_executes_one_coherent_unit_motion() -> None:
    def compound(asset_id: str) -> StoryAssetActivation:
        return _activation(
            asset_id, start=0.1, peak=0.25, settle=0.5, end=0.55,
            event_id="E1", event_order=1, roles=["LEADER"],
        ).model_copy(update={
            "semantic_unit_id": "compound-unit",
            "compound_visual_classification": "COMPOUND_REQUIRED",
            "internal_progression_unavailable": True,
            "evidence": ["visual_identity_multi_cutout_member"],
        })

    left, right = compound("left"), compound("right")
    beat = StoryBeat(
        id="compound", scene_id="scene", start=0.0, end=0.8,
        audio_start=0.0, audio_end=0.7, narration="compound",
        primary_asset_ids=["left"], support_asset_ids=["right"], action="EXPLAIN",
        asset_activations=[left, right],
    )
    composition = CompositionBeat(
        beat_id=beat.id,
        items=[
            LayoutItem(asset_id="left", x=0.4, y=0.5, width=0.2, height=0.2),
            LayoutItem(asset_id="right", x=0.6, y=0.5, width=0.2, height=0.2),
        ],
    )
    flow = SemanticEventFlow(
        event_id="E1", order=1, leader_asset_ids=("left", "right"),
        stages=(EventFlowStage.ESTABLISH, EventFlowStage.RELEASE),
        steps=(
            EventFlowStep(EventFlowStage.ESTABLISH, focus_asset_id="left", participant_asset_ids=("left", "right")),
            EventFlowStep(EventFlowStage.RELEASE, focus_asset_id="left", participant_asset_ids=("left", "right")),
        ),
    )
    directive = ChoreographyDirective(
        beat_id=beat.id, sequence_id="sequence-001", phase=SequencePhase.SETUP,
        action="EXPLAIN", pattern=ChoreographyPattern.PROGRESSIVE_BUILD,
        hook=HookKind.OPEN, primary_asset_id="left", event_flows=(flow,),
    )
    cues = MotionPlanner().plan(
        [beat], [composition], ChoreographyPlan(directives=(directive,))
    )

    assert {cue.params["program"]["name"] for cue in cues} == {"compound_unit_coherent_reveal"}
    assert cues[0].params["program"]["keyframes"] == cues[1].params["program"]["keyframes"]
    assert all(
        cue.params["semantic_focus"]["event_flow_execution"] == "COMPOUND_UNIT_LOCK"
        for cue in cues
    )
