from __future__ import annotations

# Historical lifetime regressions now owned by Motion.

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
from app.motion.event_flow import MotionEventFlowResolver
from app.motion.lifetime import SemanticVisualLifetimeIndex
from tests.test2.support.lifetime_oracle import MotionLifetimeContract as SemanticLifetimeQA
from app.story.windows import StoryAssetActivation


def activation(asset_id: str, event_id: str, order: int, start: float, settle: float):
    peak = start + (settle - start) * 0.5
    return StoryAssetActivation(
        asset_id=asset_id,
        semantic_unit_id=asset_id,
        trigger_text=asset_id,
        trigger_char_start=order * 10,
        trigger_char_end=order * 10 + 4,
        spoken_start=start,
        spoken_end=settle,
        confidence=0.99,
        source="final_package_semantic_binding",
        policy="EXPLICIT",
        binding_type="EXPLICIT",
        semantic_event_id=event_id,
        semantic_event_order=order,
        semantic_event_roles=["LEADER"],
        phrase_start=start,
        phrase_end=settle,
        reveal_start=start,
        semantic_peak=peak,
        settle_at=settle,
        activation_policy="OWN_WINDOW",
    ).with_legacy_evidence()


def flow(
    event_id: str,
    order: int,
    focus: str,
    *,
    deps: tuple[str, ...] = (),
    handoff: tuple[str, ...] = (),
    extra: tuple[EventFlowStep, ...] = (),
):
    steps = (
        EventFlowStep(EventFlowStage.ESTABLISH, focus_asset_id=focus),
        *extra,
        EventFlowStep(EventFlowStage.RELEASE, focus_asset_id=focus),
    )
    return SemanticEventFlow(
        event_id=event_id,
        order=order,
        dependency_ids=deps,
        leader_asset_ids=(focus,),
        stages=tuple(step.stage for step in steps),
        steps=steps,
        handoff_to_event_ids=handoff,
        handoff_to_event_id=handoff[0] if len(handoff) == 1 else None,
    )


def directive(*flows: SemanticEventFlow):
    return ChoreographyDirective(
        beat_id="beat",
        sequence_id="sequence",
        phase=SequencePhase.ACTION,
        action="EXPLAIN",
        pattern=ChoreographyPattern.PROGRESSIVE_BUILD,
        hook=HookKind.OPEN,
        primary_asset_id=flows[0].primary_leader_asset_id,
        event_flows=flows,
    )


def beat(rows, duration: float = 2.0):
    ids = [row.asset_id for row in rows]
    return StoryBeat(
        id="beat",
        scene_id="scene",
        start=0.0,
        end=duration,
        audio_start=0.0,
        audio_end=duration - 0.05,
        narration="semantic lifetime",
        primary_asset_ids=ids[:1],
        support_asset_ids=ids[1:],
        action="EXPLAIN",
        asset_activations=rows,
    )


def index(story: StoryBeat, choreo: ChoreographyDirective):
    resolver = MotionEventFlowResolver()
    assignments = resolver.resolve_all(
        choreo,
        [row.asset_id for row in story.asset_activations],
        semantic_event_by_asset={
            row.asset_id: row.semantic_event_id for row in story.asset_activations
        },
    )
    return SemanticVisualLifetimeIndex.build(
        beat=story,
        directive=choreo,
        assignments=assignments,
    )


def add(asset_id: str):
    return EventFlowStep(
        EventFlowStage.ADD,
        focus_asset_id=asset_id,
        participant_asset_ids=(asset_id,),
    )


def relation(source: str, target: str, *, stage=EventFlowStage.INTERACT):
    return EventFlowStep(
        stage,
        focus_asset_id=source if stage == EventFlowStage.INTERACT else target,
        participant_asset_ids=(source, target),
        source_asset_id=source,
        target_asset_id=target,
        relationship="PERSISTS_OVER_TIME",
        semantic_action="LOOP",
        authority="FINAL_PACKAGE_ASSET_RELATION",
    )


@pytest.mark.parametrize(
    ("name", "build_case", "protected"),
    [
        (
            "same_asset_reuse",
            lambda: (
                beat([activation("shared", "E1", 1, 0.1, 0.35)]),
                directive(
                    flow("E1", 1, "shared", handoff=("E2",)),
                    flow("E2", 2, "shared", deps=("E1",)),
                ),
                "shared",
            ),
            True,
        ),
        (
            "shared_support",
            lambda: (
                beat([
                    activation("support", "E1", 1, 0.1, 0.35),
                    activation("result", "E2", 2, 0.8, 1.2),
                ]),
                directive(
                    flow("E1", 1, "support", handoff=("E2",)),
                    flow("E2", 2, "result", deps=("E1",), extra=(add("support"),)),
                ),
                "support",
            ),
            True,
        ),
        (
            "relation_source",
            lambda: (
                beat([
                    activation("program", "E1", 1, 0.1, 0.4),
                    activation("calendar", "E2", 2, 0.75, 1.15),
                ]),
                directive(
                    flow(
                        "E1",
                        1,
                        "program",
                        handoff=("E2",),
                        extra=(relation("program", "calendar"),),
                    ),
                    flow("E2", 2, "calendar", deps=("E1",)),
                ),
                "program",
            ),
            True,
        ),
        (
            "relation_target",
            lambda: (
                beat([
                    activation("target", "E1", 1, 0.1, 0.35),
                    activation("source", "E2", 2, 0.8, 1.2),
                ]),
                directive(
                    flow(
                        "E1",
                        1,
                        "target",
                        handoff=("E2",),
                        extra=(relation("source", "target", stage=EventFlowStage.REACT),),
                    ),
                    flow("E2", 2, "source", deps=("E1",)),
                ),
                "target",
            ),
            True,
        ),
        (
            "simultaneous_reuse_a",
            lambda: (
                beat([
                    activation("a", "E1", 1, 0.1, 0.35),
                    activation("b", "E1", 1, 0.1, 0.35),
                    activation("c", "E2", 2, 0.7, 1.1),
                ]),
                directive(
                    flow("E1", 1, "a", handoff=("E2",), extra=(add("b"),)),
                    flow("E2", 2, "c", deps=("E1",), extra=(add("a"), add("b"))),
                ),
                "a",
            ),
            True,
        ),
        (
            "simultaneous_reuse_b",
            lambda: (
                beat([
                    activation("a", "E1", 1, 0.1, 0.35),
                    activation("b", "E1", 1, 0.1, 0.35),
                    activation("c", "E2", 2, 0.7, 1.1),
                ]),
                directive(
                    flow("E1", 1, "a", handoff=("E2",), extra=(add("b"),)),
                    flow("E2", 2, "c", deps=("E1",), extra=(add("a"), add("b"))),
                ),
                "b",
            ),
            True,
        ),
        (
            "branch_reuse",
            lambda: (
                beat([
                    activation("a", "E1", 1, 0.1, 0.3),
                    activation("left", "E2", 2, 0.6, 0.9),
                    activation("right", "E3", 3, 0.65, 0.95),
                ]),
                directive(
                    flow("E1", 1, "a", handoff=("E2", "E3")),
                    flow("E2", 2, "left", deps=("E1",), extra=(add("a"),)),
                    flow("E3", 3, "right", deps=("E1",)),
                ),
                "a",
            ),
            True,
        ),
        (
            "merge_reuse",
            lambda: (
                beat([
                    activation("shared", "E1", 1, 0.1, 0.3),
                    activation("b", "E2", 2, 0.5, 0.7),
                    activation("result", "E3", 3, 1.0, 1.3),
                ]),
                directive(
                    flow("E1", 1, "shared", handoff=("E3",)),
                    flow("E2", 2, "b", handoff=("E3",)),
                    flow("E3", 3, "result", deps=("E1", "E2"), extra=(add("shared"),)),
                ),
                "shared",
            ),
            True,
        ),
        (
            "same_beat_later_phase",
            lambda: (
                beat([
                    activation("shared", "E1", 1, 0.1, 0.35),
                    activation("later", "E2", 2, 0.7, 1.1),
                ]),
                directive(
                    flow("E1", 1, "shared", handoff=("E2",)),
                    flow("E2", 2, "later", deps=("E1",), extra=(add("shared"),)),
                ),
                "shared",
            ),
            True,
        ),
        (
            "disconnected_reintroduction",
            lambda: (
                beat([
                    activation("shared", "E1", 1, 0.1, 0.35),
                    activation("later", "E2", 2, 0.8, 1.2),
                ]),
                directive(flow("E1", 1, "shared"), flow("E2", 2, "later")),
                "shared",
            ),
            False,
        ),
        (
            "visually_similar_distinct_ids",
            lambda: (
                beat([
                    activation("server_old", "E1", 1, 0.1, 0.35),
                    activation("server_new", "E2", 2, 0.8, 1.2),
                ]),
                directive(
                    flow("E1", 1, "server_old", handoff=("E2",)),
                    flow("E2", 2, "server_new", deps=("E1",)),
                ),
                "server_old",
            ),
            False,
        ),
        (
            "no_future_use",
            lambda: (
                beat([
                    activation("old", "E1", 1, 0.1, 0.35),
                    activation("new", "E2", 2, 0.8, 1.2),
                ]),
                directive(
                    flow("E1", 1, "old", handoff=("E2",)),
                    flow("E2", 2, "new", deps=("E1",)),
                ),
                "old",
            ),
            False,
        ),
        (
            "unrelated_branch",
            lambda: (
                beat([
                    activation("old", "E1", 1, 0.1, 0.35),
                    activation("left", "E2", 2, 0.7, 1.0),
                    activation("right", "E3", 3, 0.75, 1.05),
                ]),
                directive(
                    flow("E1", 1, "old", handoff=("E2", "E3")),
                    flow("E2", 2, "left", deps=("E1",)),
                    flow("E3", 3, "right", deps=("E1",)),
                ),
                "old",
            ),
            False,
        ),
        (
            "terminal_event",
            lambda: (
                beat([activation("only", "E1", 1, 0.1, 0.4)]),
                directive(flow("E1", 1, "only")),
                "only",
            ),
            False,
        ),
    ],
    ids=lambda row: row if isinstance(row, str) else None,
)
def test_future_semantic_use_matrix(name, build_case, protected) -> None:
    story, choreo, asset_id = build_case()
    decision = index(story, choreo).for_asset(asset_id)
    assert (decision is not None) is protected, name



def test_nonpersistent_relation_counterpart_does_not_extend_source_lifetime() -> None:
    source = activation("source", "E1", 1, 0.1, 0.35)
    result = activation("result", "E2", 2, 0.8, 1.2)
    story = beat([source, result])
    causal = EventFlowStep(
        EventFlowStage.INTERACT,
        focus_asset_id="source",
        participant_asset_ids=("source", "result"),
        source_asset_id="source",
        target_asset_id="result",
        relationship="CAUSES",
        semantic_action="REVEAL",
        authority="FINAL_PACKAGE_ASSET_RELATION",
    )
    choreo = directive(
        flow("E1", 1, "source", handoff=("E2",), extra=(causal,)),
        flow("E2", 2, "result", deps=("E1",)),
    )
    assert index(story, choreo).for_asset("source") is None


def test_persistence_relation_counterpart_extends_source_lifetime() -> None:
    source = activation("source", "E1", 1, 0.1, 0.35)
    result = activation("result", "E2", 2, 0.8, 1.2)
    story = beat([source, result])
    choreo = directive(
        flow("E1", 1, "source", handoff=("E2",), extra=(relation("source", "result"),)),
        flow("E2", 2, "result", deps=("E1",)),
    )
    assert index(story, choreo).for_asset("source") is not None

def test_legacy_beat_without_event_flow_has_no_lifetime_override() -> None:
    story = beat([activation("asset", "E1", 1, 0.1, 0.35)])
    assert SemanticVisualLifetimeIndex.build(
        beat=story,
        directive=None,
        assignments={},
    ).for_asset("asset") is None


def test_planner_holds_relation_source_instead_of_terminal_exit() -> None:
    program = activation("program", "E1", 1, 0.1, 0.36)
    calendar = activation("calendar", "E2", 2, 0.8, 1.2)
    story = beat([program, calendar], duration=1.6)
    e1 = flow(
        "E1",
        1,
        "program",
        handoff=("E2",),
        extra=(relation("program", "calendar"),),
    )
    e2 = flow("E2", 2, "calendar", deps=("E1",))
    plan = ChoreographyPlan(directives=(directive(e1, e2),))
    composition = CompositionBeat(
        beat_id=story.id,
        items=[
            LayoutItem(asset_id="program", x=0.30, y=0.45, width=0.24, height=0.24),
            LayoutItem(asset_id="calendar", x=0.70, y=0.55, width=0.24, height=0.24),
        ],
    )
    cues = {cue.asset_id: cue for cue in MotionPlanner().plan([story], [composition], plan)}
    assert not [segment for segment in cues["program"].segments if segment.phase == "EXIT"]
    assert cues["program"].params["semantic_lifetime"]["mode"] == "HOLD_THROUGH_FUTURE_USE"


def test_asset_without_future_use_keeps_legacy_terminal_exit() -> None:
    old = activation("old", "E1", 1, 0.1, 0.35)
    new = activation("new", "E2", 2, 0.8, 1.2)
    story = beat([old, new])
    plan = ChoreographyPlan(directives=(directive(
        flow("E1", 1, "old", handoff=("E2",)),
        flow("E2", 2, "new", deps=("E1",)),
    ),))
    composition = CompositionBeat(
        beat_id=story.id,
        items=[
            LayoutItem(asset_id="old", x=0.3, y=0.5, width=0.2, height=0.2),
            LayoutItem(asset_id="new", x=0.7, y=0.5, width=0.2, height=0.2),
        ],
    )
    cues = {cue.asset_id: cue for cue in MotionPlanner().plan([story], [composition], plan)}
    exits = [segment for segment in cues["old"].segments if segment.phase == "EXIT"]
    assert len(exits) == 1


def test_semantic_lifetime_qa_rejects_legacy_premature_exit_plan() -> None:
    program = activation("program", "E1", 1, 0.1, 0.36)
    calendar = activation("calendar", "E2", 2, 0.8, 1.2)
    story = beat([program, calendar], duration=1.6)
    choreo = ChoreographyPlan(directives=(directive(
        flow(
            "E1",
            1,
            "program",
            handoff=("E2",),
            extra=(relation("program", "calendar"),),
        ),
        flow("E2", 2, "calendar", deps=("E1",)),
    ),))
    premature = MotionCue(
        beat_id=story.id,
        asset_id="program",
        kind="program_v3",
        start=0.1,
        end=0.36,
        params={},
        segments=[MotionSegment(
            phase="EXIT",
            start=0.55,
            end=0.75,
            program={"terminal_behavior": "LEAVE", "keyframes": []},
            semantic_event_id="E1",
        )],
    )
    report = SemanticLifetimeQA().inspect(
        story=[story],
        motion=[premature],
        choreography=choreo,
    )
    assert not report.ok
    assert report.violations[0].code == "PREMATURE_SEMANTIC_EXIT"
