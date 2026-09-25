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
    MotionCue,
    MotionSegment,
    StoryBeat,
    StoryRelation,
    StorySemanticContext,
    Transcript,
    TranscriptWord,
)
from app.motion import MotionPlanner
from app.motion.event_flow import MotionEventAssignment
from app.motion.models import MotionKeyframe, MotionProgram
from app.motion.timing import (
    GOLDEN_MAJOR,
    GOLDEN_MINOR,
    comfort_gain,
    max_comfort_displacement,
    motion_comfort,
)
from app.qa import MotionInteractionQA, RenderedMotionQA
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
    assert "PAYOFF" in c
    if "ENTRY" in c:
        assert c["ENTRY"].end <= c["PAYOFF"].start + 1e-9
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
    source = next(
        segment
        for row in cues
        for segment in row.segments
        if row.asset_id == "a" and segment.phase == "INTERACT"
    )
    bad = cue.segments[index].model_copy(
        update={"start": source.end + 0.01, "end": source.end + 0.15}
    )
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


@pytest.mark.parametrize(
    ("cue_end", "handoff_deadline"),
    [
        (37.759, 37.087),
        (46.037, 45.749),
        (58.410, 57.572),
        (87.734, 87.117),
    ],
)
def test_entry_is_fitted_before_real_diagnostic_handoff(
    cue_end: float,
    handoff_deadline: float,
) -> None:
    """Regression for diagnostic job 3d5bd61b707b43fe8507eeca5e73bbe4."""
    cue_start = handoff_deadline - 0.16
    cue = MotionCue(
        beat_id="beat",
        asset_id="asset",
        kind="program_v3",
        start=cue_start,
        end=cue_end,
        params={"engine_version": 3},
    )
    program = MotionProgram(
        name="entry",
        settle_progress=1.0,
        keyframes=(
            MotionKeyframe(0.0, -0.05, 0.0, 0.92, "ease_out_cubic"),
            MotionKeyframe(0.55, -0.02, 0.0, 0.98, "ease_out_cubic"),
            MotionKeyframe(1.0, 0.0, 0.0, 1.0, "smoothstep"),
        ),
    )
    assignment = MotionEventAssignment(
        event_id="E1",
        event_order=1,
        stage=EventFlowStage.ESTABLISH,
        step_index=0,
        focus_asset_id="asset",
        source_asset_id=None,
        target_asset_id=None,
        result_asset_id=None,
        relationship=None,
        semantic_action="ESTABLISH",
        authority="FINAL_PACKAGE_SEMANTIC_EVENT",
        involvement="FOCUS",
    )

    segment = MotionPlanner._entry_segment_before_handoff(
        cue=cue,
        entry_program=program,
        assignment=assignment,
        deadline=handoff_deadline,
    )

    assert segment is not None
    assert segment.start == pytest.approx(cue_start)
    assert segment.end == pytest.approx(handoff_deadline)
    assert segment.end <= handoff_deadline
    assert segment.end < cue.end
    final = segment.program["keyframes"][-1]
    assert final["dx"] == pytest.approx(0.0)
    assert final["dy"] == pytest.approx(0.0)
    assert final["scale"] == pytest.approx(1.0)
    assert abs(segment.program["keyframes"][0]["dx"]) < 0.05

    report = MotionInteractionQA().inspect(
        story=[],
        motion=[cue.model_copy(update={"segments": [segment]})],
    )
    assert report.ok, report.violations


def test_entry_with_no_pre_handoff_time_snaps_to_composition() -> None:
    cue = MotionCue(
        beat_id="beat",
        asset_id="asset",
        kind="program_v3",
        start=10.0,
        end=10.4,
        params={"engine_version": 3},
    )
    program = MotionProgram(
        name="entry",
        settle_progress=1.0,
        keyframes=(
            MotionKeyframe(0.0, -0.04, 0.0, 0.95),
            MotionKeyframe(1.0, 0.0, 0.0, 1.0),
        ),
    )
    assignment = MotionEventAssignment(
        event_id="E1",
        event_order=1,
        stage=EventFlowStage.ESTABLISH,
        step_index=0,
        focus_asset_id="asset",
        source_asset_id=None,
        target_asset_id=None,
        result_asset_id=None,
        relationship=None,
        semantic_action="ESTABLISH",
        authority="FINAL_PACKAGE_SEMANTIC_EVENT",
        involvement="FOCUS",
    )

    assert MotionPlanner._entry_segment_before_handoff(
        cue=cue,
        entry_program=program,
        assignment=assignment,
        deadline=10.0,
    ) is None


def test_event_motion_has_perceptual_floor() -> None:
    beat, composition, choreography = _fixture()
    cues = MotionPlanner().plan([beat], [composition], choreography)
    by_id = {cue.asset_id: cue for cue in cues}
    interact = next(row for row in by_id["a"].segments if row.phase == "INTERACT")
    react = next(row for row in by_id["b"].segments if row.phase == "REACT")
    payoff = next(row for row in by_id["c"].segments if row.phase == "PAYOFF")

    for segment in (interact, react):
        peak = max(
            (float(frame["dx"]) ** 2 + float(frame["dy"]) ** 2) ** 0.5
            for frame in segment.program["keyframes"]
        )
        duration = segment.end - segment.start
        comfort_cap = max_comfort_displacement(
            segment.phase,
            duration * GOLDEN_MINOR,
        )
        base_floor = 0.030 if segment.phase == "INTERACT" else 0.026
        floor = min(
            base_floor * comfort_gain(segment.phase, duration),
            comfort_cap,
        )
        assert peak >= floor - 1e-6
        assert peak <= comfort_cap + 1e-6
        assert segment.program["keyframes"][1]["progress"] == pytest.approx(GOLDEN_MAJOR)
        assert duration >= motion_comfort(segment.phase).minimum_seconds
    payoff_scale = max(
        abs(float(frame["scale"]) - 1.0) for frame in payoff.program["keyframes"]
    )
    payoff_duration = payoff.end - payoff.start
    payoff_cap = max_comfort_displacement(
        "PAYOFF", payoff_duration * GOLDEN_MINOR
    ) / min(composition.items[2].width, composition.items[2].height)
    expected_payoff = min(
        0.075 * comfort_gain("PAYOFF", payoff_duration),
        payoff_cap,
    )
    assert payoff_scale == pytest.approx(expected_payoff, abs=1e-6)


def test_handoff_creates_real_exit_for_outgoing_asset() -> None:
    cue = MotionCue(
        beat_id="beat", asset_id="old", kind="program_v3",
        start=1.0, end=1.2, params={"engine_version": 3},
    )
    assignment = MotionEventAssignment(
        event_id="E1", event_order=1, stage=EventFlowStage.INTERACT,
        step_index=1, focus_asset_id="old",
        source_asset_id="old", target_asset_id="target", result_asset_id=None,
        relationship="CONNECTS", semantic_action="CONNECT",
        authority="FINAL_PACKAGE_ASSET_RELATION", involvement="SOURCE",
        handoff_to_event_ids=("E2",), handoff_to_asset_ids=("new",),
        handoff_to_event_id="E2", handoff_to_asset_id="new",
    )
    old = LayoutItem(asset_id="old", x=0.25, y=0.5, width=0.2, height=0.3)
    new = LayoutItem(asset_id="new", x=0.75, y=0.5, width=0.2, height=0.3)
    segment = MotionPlanner._exit_segment_before_handoff(
        cue=cue,
        assignment=assignment,
        deadline=2.0,
        item=old,
        items_by_id={"old": old, "new": new},
        existing_segments=[],
    )
    assert segment is not None
    assert segment.phase == "EXIT"
    assert segment.end == pytest.approx(2.0)
    assert segment.end - segment.start >= motion_comfort("EXIT").minimum_seconds
    golden = segment.program["keyframes"][1]
    assert golden["progress"] == pytest.approx(GOLDEN_MAJOR)
    final = segment.program["keyframes"][-1]
    assert float(golden["dx"]) == pytest.approx(float(final["dx"]) * GOLDEN_MAJOR)
    assert float(final["dx"]) < -0.035
    assert float(final["scale"]) < 1.0
    report = MotionInteractionQA().inspect(
        story=[], motion=[cue.model_copy(update={"segments": [segment]})],
    )
    assert report.ok, report.violations


def test_motion_interaction_qa_rejects_new_collision_from_stronger_motion() -> None:
    beat, composition, choreography = _fixture()
    close_composition = CompositionBeat(
        beat_id=composition.beat_id,
        items=[
            # Authored boxes remain separate by 0.5% of canvas width; the stronger
            # relation motion should be what creates the collision.
            LayoutItem(asset_id="a", x=0.315, y=0.50, width=0.18, height=0.22),
            LayoutItem(asset_id="b", x=0.50, y=0.50, width=0.18, height=0.22),
            LayoutItem(asset_id="c", x=0.80, y=0.50, width=0.18, height=0.22),
        ],
    )
    cues = MotionPlanner().plan([beat], [close_composition], choreography)
    report = MotionInteractionQA().inspect(
        story=[beat], motion=cues, composition=[close_composition],
    )
    assert not report.ok
    assert any(row.code == "MOTION_CREATES_COLLISION" for row in report.violations)


def test_motion_interaction_qa_accepts_readable_motion_with_safe_spacing() -> None:
    beat, composition, choreography = _fixture()
    cues = MotionPlanner().plan([beat], [composition], choreography)
    report = MotionInteractionQA().inspect(
        story=[beat], motion=cues, composition=[composition],
    )
    assert report.ok, report.violations


def test_tight_handoff_omits_rushed_exit_instead_of_accelerating() -> None:
    cue = MotionCue(
        beat_id="beat", asset_id="old", kind="program_v3",
        start=1.0, end=1.18, params={"engine_version": 3},
    )
    assignment = MotionEventAssignment(
        event_id="E1", event_order=1, stage=EventFlowStage.INTERACT,
        step_index=1, focus_asset_id="old",
        source_asset_id="old", target_asset_id="target", result_asset_id=None,
        relationship="CONNECTS", semantic_action="CONNECT",
        authority="FINAL_PACKAGE_ASSET_RELATION", involvement="SOURCE",
        handoff_to_event_ids=("E2",), handoff_to_asset_ids=("new",),
        handoff_to_event_id="E2", handoff_to_asset_id="new",
    )
    old = LayoutItem(asset_id="old", x=0.25, y=0.5, width=0.2, height=0.3)
    new = LayoutItem(asset_id="new", x=0.75, y=0.5, width=0.2, height=0.3)
    segment = MotionPlanner._exit_segment_before_handoff(
        cue=cue,
        assignment=assignment,
        deadline=1.50,
        item=old,
        items_by_id={"old": old, "new": new},
        existing_segments=[],
    )
    assert segment is None



def test_entry_scale_respects_same_comfort_speed_contract_as_encoded_qa() -> None:
    item = LayoutItem(asset_id="large", x=0.5, y=0.5, width=0.72, height=0.82)
    program = MotionProgram(
        name="large_entry",
        settle_progress=0.82,
        keyframes=(
            MotionKeyframe(0.0, -0.04, 0.0, 1.20, "ease_in_out_cubic"),
            MotionKeyframe(0.50, -0.02, 0.0, 1.10, "ease_in_out_cubic"),
            MotionKeyframe(0.82, 0.0, 0.0, 1.0, "smoothstep"),
            MotionKeyframe(1.0, 0.0, 0.0, 1.0, "smoothstep"),
        ),
    )
    duration = 0.30
    fitted = MotionPlanner._ensure_readable_entry(program, item=item, duration=duration)
    segment = MotionSegment(
        phase="ENTRY",
        start=0.0,
        end=duration,
        program=fitted.to_payload(),
    )
    speed = RenderedMotionQA._max_normalized_keyframe_speed(
        segment,
        duration=duration,
        item_width=item.width,
        item_height=item.height,
    )
    limit = motion_comfort("ENTRY").max_normalized_speed * 1.08
    assert speed <= limit + 1e-6


def test_entry_completes_before_semantic_relation_phase_on_same_asset() -> None:
    beat, composition, choreography = _fixture()
    cues = MotionPlanner().plan([beat], [composition], choreography)
    for cue in cues:
        entry = next((row for row in cue.segments if row.phase == "ENTRY"), None)
        if entry is None:
            continue
        for segment in cue.segments:
            if segment.phase in {"INTERACT", "REACT", "PAYOFF"}:
                assert segment.start >= entry.end - 1e-9
