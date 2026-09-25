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
from app.models import CompositionBeat, LayoutItem, MotionCue, MotionSegment, StoryBeat
from app.motion import MotionPlanner
from app.motion.rhythm import MIN_FOCUS_OVERLAP_SECONDS, ReferenceRhythmPolicy
from app.motion.timing import MotionTimingPolicy
from app.qa import ChoreographyRhythmQA
from app.story.windows import StoryAssetActivation


def _beat(
    beat_id: str,
    *,
    start: float,
    end: float,
    narration: str,
    action: str = "EXPLAIN",
    activations: list[StoryAssetActivation] | None = None,
    primary: list[str] | None = None,
    support: list[str] | None = None,
) -> StoryBeat:
    return StoryBeat(
        id=beat_id,
        scene_id=f"scene-{beat_id}",
        start=start,
        end=end,
        audio_start=start,
        audio_end=end,
        narration=narration,
        primary_asset_ids=primary or [],
        support_asset_ids=support or [],
        action=action,
        asset_activations=activations or [],
    )


def _directive(
    beat_id: str,
    *,
    action: str = "EXPLAIN",
    hook: HookKind = HookKind.NONE,
    tension: float = 0.0,
    pacing_bias: float = 1.0,
    primary: str | None = None,
    event_flows: tuple[SemanticEventFlow, ...] = (),
) -> ChoreographyDirective:
    return ChoreographyDirective(
        beat_id=beat_id,
        sequence_id="seq",
        phase=SequencePhase.ACTION,
        action=action,
        pattern=ChoreographyPattern.STANDARD,
        hook=hook,
        tension=tension,
        pacing_bias=pacing_bias,
        primary_asset_id=primary,
        event_flows=event_flows,
    )


def _activation(
    asset_id: str,
    *,
    reveal: float,
    settle: float,
    role: str,
    event_id: str = "E1",
    event_order: int = 1,
    semantic_unit_id: str | None = None,
) -> StoryAssetActivation:
    duration = max(0.06, settle - reveal)
    peak = reveal + duration * 0.55
    return StoryAssetActivation(
        asset_id=asset_id,
        semantic_unit_id=semantic_unit_id or asset_id,
        trigger_text=asset_id,
        trigger_char_start=event_order * 10,
        trigger_char_end=event_order * 10 + 5,
        spoken_start=reveal,
        spoken_end=settle,
        confidence=0.99,
        source="final_package_semantic_binding",
        policy="EXPLICIT",
        binding_type="EXPLICIT",
        semantic_event_id=event_id,
        semantic_event_order=event_order,
        semantic_event_roles=[role],
        phrase_start=reveal,
        phrase_end=settle,
        reveal_start=reveal,
        semantic_peak=min(settle, peak),
        settle_at=settle,
        activation_policy="OWN_WINDOW",
    ).with_legacy_evidence()


def _layout(beat_id: str, ids: list[str]) -> CompositionBeat:
    count = max(1, len(ids))
    return CompositionBeat(
        beat_id=beat_id,
        items=[
            LayoutItem(
                asset_id=asset_id,
                x=(index + 1) / (count + 1),
                y=0.5 if index % 2 == 0 else 0.72,
                width=0.12,
                height=0.16,
                z=index,
            )
            for index, asset_id in enumerate(ids)
        ],
    )


def test_reference_rhythm_smooths_isolated_pace_whiplash() -> None:
    beats = [
        _beat("b1", start=0.0, end=2.0, narration="one two three four"),
        _beat(
            "b2",
            start=2.0,
            end=2.55,
            narration="one two three four five six seven eight nine ten",
        ),
        _beat("b3", start=2.55, end=4.55, narration="one two three four"),
    ]
    plan = ChoreographyPlan(
        directives=tuple(_directive(beat.id) for beat in beats)
    )

    decisions = ReferenceRhythmPolicy().plan(beats, plan, MotionTimingPolicy())

    assert decisions["b2"].raw_pace_tier == "snap"
    assert ReferenceRhythmPolicy.tier_distance(
        decisions["b1"].pace_tier, decisions["b2"].pace_tier
    ) <= 1
    assert ReferenceRhythmPolicy.tier_distance(
        decisions["b2"].pace_tier, decisions["b3"].pace_tier
    ) <= 1


def test_reference_rhythm_preserves_authored_hook_contrast() -> None:
    beats = [
        _beat("b1", start=0.0, end=2.0, narration="one two three"),
        _beat(
            "b2",
            start=2.0,
            end=2.45,
            narration="one two three four five six seven eight nine",
            action="BLOCK",
        ),
    ]
    plan = ChoreographyPlan(
        directives=(
            _directive("b1"),
            _directive("b2", action="BLOCK", hook=HookKind.REHOOK, tension=0.92),
        )
    )

    decisions = ReferenceRhythmPolicy().plan(beats, plan, MotionTimingPolicy())

    assert decisions["b2"].pace_tier == decisions["b2"].raw_pace_tier
    assert decisions["b2"].smoothing_reason == "authored_attention_contrast"


def test_overlapping_story_windows_share_one_visual_focus_leader() -> None:
    leader = _activation("hero", reveal=0.10, settle=0.50, role="LEADER")
    participant = _activation("support", reveal=0.26, settle=0.62, role="PARTICIPANT")
    assert 0.50 - 0.26 > MIN_FOCUS_OVERLAP_SECONDS
    beat = _beat(
        "overlap",
        start=0.0,
        end=1.0,
        narration="hero support",
        activations=[leader, participant],
        primary=["hero"],
        support=["support"],
    )
    composition = _layout(beat.id, ["hero", "support"])

    choreography = ChoreographyPlan(
        directives=(_directive(beat.id, primary="hero"),)
    )
    cues = MotionPlanner().plan([beat], [composition], choreography)
    focus = {cue.asset_id: cue.params["semantic_focus"] for cue in cues}

    assert focus["hero"]["cohort_gain"] == pytest.approx(1.0)
    assert focus["hero"]["cohort_role"] == "leader"
    assert focus["support"]["cohort_gain"] < 0.72
    assert focus["support"]["cohort_role"] in {"participant", "secondary", "quiet"}
    report = ChoreographyRhythmQA().inspect(story=[beat], motion=cues)
    assert report.ok, report.violations
    assert report.checked_entry_cohorts == 1


def test_sequential_story_windows_keep_independent_focus() -> None:
    first = _activation("first", reveal=0.10, settle=0.34, role="LEADER", event_id="E1")
    second = _activation("second", reveal=0.35, settle=0.64, role="LEADER", event_id="E2", event_order=2)
    beat = _beat(
        "sequential",
        start=0.0,
        end=1.0,
        narration="first second",
        activations=[first, second],
        primary=["first"],
        support=["second"],
    )
    composition = _layout(beat.id, ["first", "second"])

    choreography = ChoreographyPlan(
        directives=(_directive(beat.id, primary="first"),)
    )
    cues = MotionPlanner().plan([beat], [composition], choreography)
    focus = {cue.asset_id: cue.params["semantic_focus"] for cue in cues}

    assert focus["first"]["cohort_role"] == "independent"
    assert focus["second"]["cohort_role"] == "independent"
    assert focus["first"]["cohort_gain"] == pytest.approx(1.0)
    assert focus["second"]["cohort_gain"] == pytest.approx(1.0)


def test_dense_twenty_asset_overlap_has_one_leader_and_quiet_context() -> None:
    activations: list[StoryAssetActivation] = []
    ids = [f"asset-{index:02d}" for index in range(20)]
    for index, asset_id in enumerate(ids):
        role = "LEADER" if index == 0 else ("CONTEXT" if index >= 12 else "PARTICIPANT")
        activations.append(
            _activation(
                asset_id,
                reveal=0.10 + index * 0.008,
                settle=0.52 + index * 0.004,
                role=role,
            )
        )
    beat = _beat(
        "dense",
        start=0.0,
        end=1.6,
        narration=" ".join(ids),
        activations=activations,
        primary=[ids[0]],
        support=ids[1:],
    )
    composition = _layout(beat.id, ids)

    choreography = ChoreographyPlan(
        directives=(_directive(beat.id, primary=ids[0]),)
    )
    cues = MotionPlanner().plan([beat], [composition], choreography)
    focus = [cue.params["semantic_focus"] for cue in cues]

    assert len(cues) == 20
    assert sum(row["cohort_role"] == "leader" for row in focus) == 1
    assert max(row["cohort_gain"] for row in focus) == pytest.approx(1.0)
    assert min(row["cohort_gain"] for row in focus) <= 0.18
    report = ChoreographyRhythmQA().inspect(story=[beat], motion=cues)
    assert report.ok, report.violations


def test_explicit_semantic_timeline_never_duplicates_accent_inside_entry() -> None:
    source = _activation("source", reveal=0.10, settle=0.34, role="LEADER")
    target = _activation("target", reveal=0.40, settle=0.68, role="PARTICIPANT")
    flow = SemanticEventFlow(
        event_id="E1",
        order=1,
        leader_asset_ids=("source",),
        participant_asset_ids=("target",),
        stages=(EventFlowStage.ESTABLISH, EventFlowStage.INTERACT, EventFlowStage.REACT, EventFlowStage.RELEASE),
        steps=(
            EventFlowStep(EventFlowStage.ESTABLISH, focus_asset_id="source", participant_asset_ids=("source",)),
            EventFlowStep(
                EventFlowStage.INTERACT,
                focus_asset_id="source",
                participant_asset_ids=("source", "target"),
                source_asset_id="source",
                target_asset_id="target",
                semantic_action="CONNECT",
                relationship="CAUSES",
                authority="FINAL_PACKAGE_ASSET_RELATION",
                spoken_start=0.48,
                spoken_end=0.62,
            ),
            EventFlowStep(
                EventFlowStage.REACT,
                focus_asset_id="target",
                participant_asset_ids=("source", "target"),
                source_asset_id="source",
                target_asset_id="target",
                semantic_action="CONNECT",
                relationship="CAUSES",
                authority="FINAL_PACKAGE_ASSET_RELATION",
                spoken_start=0.50,
                spoken_end=0.66,
            ),
            EventFlowStep(EventFlowStage.RELEASE, focus_asset_id="target", participant_asset_ids=("target",)),
        ),
    )
    beat = _beat(
        "relation",
        start=0.0,
        end=1.0,
        narration="source connects target",
        activations=[source, target],
        primary=["source"],
        support=["target"],
    )
    choreography = ChoreographyPlan(
        directives=(_directive("relation", action="CONNECT", primary="source", event_flows=(flow,)),)
    )
    cues = MotionPlanner().plan([beat], [_layout(beat.id, ["source", "target"])], choreography)

    for cue in cues:
        focus = cue.params["semantic_focus"]
        if focus["event_flow_execution"] != "EXPLICIT_TIMELINE":
            continue
        assert not str(cue.params["program"]["name"]).startswith("event_chain_")
    assert any(segment.phase == "INTERACT" for cue in cues for segment in cue.segments)
    assert any(segment.phase == "REACT" for cue in cues for segment in cue.segments)
    report = ChoreographyRhythmQA().inspect(
        story=[beat], motion=cues, choreography=choreography
    )
    assert report.ok, report.violations


def test_fallback_event_flow_can_still_express_semantics_inside_entry() -> None:
    flow = SemanticEventFlow(
        event_id="E1",
        order=1,
        leader_asset_ids=("hero",),
        stages=(EventFlowStage.ESTABLISH, EventFlowStage.INTERACT, EventFlowStage.RELEASE),
        steps=(
            EventFlowStep(EventFlowStage.ESTABLISH, focus_asset_id="hero", participant_asset_ids=("hero",)),
            EventFlowStep(
                EventFlowStage.INTERACT,
                focus_asset_id="hero",
                participant_asset_ids=("hero",),
                semantic_action="EMPHASIZE",
            ),
            EventFlowStep(EventFlowStage.RELEASE, focus_asset_id="hero", participant_asset_ids=("hero",)),
        ),
    )
    beat = _beat(
        "fallback",
        start=0.0,
        end=1.0,
        narration="hero",
        primary=["hero"],
    )
    choreography = ChoreographyPlan(
        directives=(_directive("fallback", primary="hero", event_flows=(flow,)),)
    )

    cue = MotionPlanner().plan([beat], [_layout(beat.id, ["hero"])], choreography)[0]

    assert cue.params["semantic_focus"]["event_flow_execution"] == "ENTRY_FALLBACK"
    assert str(cue.params["program"]["name"]).startswith("event_chain_")
    assert not any(segment.phase in {"INTERACT", "REACT", "PAYOFF"} for segment in cue.segments)


def test_rhythm_qa_rejects_duplicate_explicit_semantic_entry_accent() -> None:
    beat = _beat("qa", start=0.0, end=1.0, narration="qa", primary=["hero"])
    cue = MotionCue(
        beat_id=beat.id,
        asset_id="hero",
        kind="program_v3",
        start=0.0,
        end=0.4,
        params={
            "pace_tier": "balanced",
            "program": {"name": "event_chain_interact_slide"},
            "semantic_focus": {
                "event_flow_execution": "EXPLICIT_TIMELINE",
                "cohort_gain": 1.0,
                "cohort_role": "leader",
            },
        },
        segments=[
            MotionSegment(
                phase="ENTRY",
                start=0.0,
                end=0.4,
                program={"name": "entry", "keyframes": [{"progress": 0.0}, {"progress": 1.0}]},
            )
        ],
    )

    report = ChoreographyRhythmQA().inspect(story=[beat], motion=[cue])

    assert not report.ok
    assert any(row.code == "DUPLICATE_SEMANTIC_ENTRY_ACCENT" for row in report.violations)


def test_short_and_long_beats_keep_story_timing_and_composition_exact() -> None:
    short_activation = _activation("short", reveal=0.0, settle=0.24, role="LEADER")
    long_activation = _activation("long", reveal=0.5, settle=0.82, role="LEADER")
    short = _beat(
        "short",
        start=0.0,
        end=0.5,
        narration="fast phrase",
        activations=[short_activation],
        primary=["short"],
    )
    long = _beat(
        "long",
        start=0.5,
        end=8.5,
        narration="slow phrase with plenty of room to read the visual without continuous motion",
        activations=[long_activation],
        primary=["long"],
    )
    compositions = [_layout("short", ["short"]), _layout("long", ["long"])]

    choreography = ChoreographyPlan(
        directives=(_directive("short", primary="short"), _directive("long", primary="long"))
    )
    cues = MotionPlanner().plan([short, long], compositions, choreography)
    by_id = {cue.asset_id: cue for cue in cues}

    assert by_id["short"].start == pytest.approx(0.0)
    assert by_id["long"].start == pytest.approx(0.5)
    for cue in cues:
        final = cue.params["program"]["keyframes"][-1]
        assert final["dx"] == pytest.approx(0.0)
        assert final["dy"] == pytest.approx(0.0)
        assert final["scale"] == pytest.approx(1.0)


def test_repeated_asset_across_beats_keeps_same_asset_continuity_without_phantom_focus() -> None:
    first_activation = _activation("same", reveal=0.1, settle=0.35, role="LEADER", event_id="E1")
    second_activation = _activation("same", reveal=1.1, settle=1.40, role="LEADER", event_id="E2", event_order=2)
    first = _beat(
        "repeat-1",
        start=0.0,
        end=1.0,
        narration="first same",
        activations=[first_activation],
        primary=["same"],
    )
    second = _beat(
        "repeat-2",
        start=1.0,
        end=2.0,
        narration="same again",
        activations=[second_activation],
        primary=["same"],
    )
    compositions = [
        CompositionBeat(beat_id=first.id, items=[LayoutItem(asset_id="same", x=0.25, y=0.5, width=0.2, height=0.2)]),
        CompositionBeat(beat_id=second.id, items=[LayoutItem(asset_id="same", x=0.75, y=0.5, width=0.2, height=0.2)]),
    ]

    choreography = ChoreographyPlan(
        directives=(_directive("repeat-1", primary="same"), _directive("repeat-2", primary="same"))
    )
    cues = MotionPlanner().plan([first, second], compositions, choreography)

    assert len(cues) == 2
    assert "continuity" in cues[1].params["program"]["name"]
    assert cues[0].params["semantic_focus"]["semantic_event_id"] == "E1"
    assert cues[1].params["semantic_focus"]["semantic_event_id"] == "E2"
    for cue in cues:
        final = cue.params["program"]["keyframes"][-1]
        assert final["dx"] == pytest.approx(0.0)
        assert final["dy"] == pytest.approx(0.0)
        assert final["scale"] == pytest.approx(1.0)
