"""Sprint 3 event-local relation ownership, using Story-proven carriers."""

from dataclasses import replace

from app.choreography.event_flow import SemanticEventFlowPlanner
from app.choreography.models import EventFlowStage, InteractionIntent
from app.models import AssetActivation, StoryBeat, StoryEventAuthority


def _activation(asset: str, event: str, order: int, role: str) -> AssetActivation:
    return AssetActivation(
        asset_id=asset, semantic_unit_id=asset,
        semantic_event_id=event, semantic_event_order=order,
        semantic_event_roles=[role], source="unified_final_package",
        policy="EXPLICIT", spoken_start=float(order),
        spoken_end=float(order) + 0.5, confidence=0.99,
    )


def _relation(kind: str = "LEADS_TO") -> InteractionIntent:
    return InteractionIntent(
        semantic_action="REVEAL", relationship=kind,
        subject_asset_id="actor", object_asset_id="target",
        result_asset_id="target", authority="FINAL_PACKAGE_ASSET_RELATION",
        confidence=0.99, executable=True,
    )


def test_result_first_relation_executes_in_source_event_and_keeps_early_payoff():
    beat = StoryBeat(
        id="beat", scene_id="scene", start=0, end=3,
        narration="result first, actor later", primary_asset_ids=["target", "actor"],
        action="REVEAL", asset_activations=[
            _activation("target", "E1", 1, "RESULT"),
            _activation("actor", "E2", 2, "LEADER"),
        ],
        event_authorities=[
            StoryEventAuthority(event_id="E1", sequence_order=1,
                                result_asset_ids=["target"]),
            StoryEventAuthority(event_id="E2", sequence_order=2,
                                leader_asset_ids=["actor"], dependency_ids=["E1"]),
        ],
    )
    flows = SemanticEventFlowPlanner().compile(
        beat=beat, interactions=(_relation(),), transitions=(),
    )
    assert [flow.event_id for flow in flows] == ["E1", "E2"]
    assert EventFlowStage.PAYOFF in flows[0].stages
    assert EventFlowStage.INTERACT not in flows[0].stages
    assert EventFlowStage.ESTABLISH in flows[1].stages
    assert EventFlowStage.INTERACT in flows[1].stages
    assert flows[1].interactions[0].subject_asset_id == "actor"
    assert flows[0].result_asset_ids == ("target",)


def test_no_typed_authority_preserves_legacy_event_assignment():
    beat = StoryBeat(
        id="beat", scene_id="scene", start=0, end=3,
        narration="legacy", primary_asset_ids=["target", "actor"],
        action="REVEAL", asset_activations=[
            _activation("target", "E1", 1, "RESULT"),
            _activation("actor", "E2", 2, "LEADER"),
        ],
    )
    flows = SemanticEventFlowPlanner().compile(
        beat=beat, interactions=(_relation(),), transitions=(),
    )
    assert EventFlowStage.INTERACT in flows[0].stages


def test_comparison_keeps_existing_symmetric_relation_stage():
    beat = StoryBeat(
        id="beat", scene_id="scene", start=0, end=3,
        narration="parallel", primary_asset_ids=["actor", "target"],
        action="COMPARE", asset_activations=[
            _activation("actor", "E1", 1, "LEADER"),
            _activation("target", "E1", 1, "PARTICIPANT"),
        ],
        event_authorities=[StoryEventAuthority(
            event_id="E1", sequence_order=1,
            leader_asset_ids=["actor"], participant_asset_ids=["target"],
            relation_kinds=["PARALLEL_CAUSES"],
        )],
    )
    flows = SemanticEventFlowPlanner().compile(
        beat=beat, interactions=(_relation("PARALLEL_CAUSES"),), transitions=(),
    )
    assert EventFlowStage.INTERACT in flows[0].stages
    assert EventFlowStage.REACT not in flows[0].stages


def test_missing_target_carrier_cannot_create_event_specific_interaction():
    beat = StoryBeat(
        id="beat", scene_id="scene", start=0, end=2,
        narration="actor", primary_asset_ids=["actor"], action="REVEAL",
        asset_activations=[_activation("actor", "E1", 1, "LEADER")],
        event_authorities=[StoryEventAuthority(
            event_id="E1", sequence_order=1, leader_asset_ids=["actor"],
        )],
    )
    flows = SemanticEventFlowPlanner().compile(
        beat=beat, interactions=(_relation(),), transitions=(),
    )
    assert EventFlowStage.INTERACT not in flows[0].stages
    assert flows[0].leader_asset_ids == ("actor",)


def test_actor_target_without_result_preserves_direction_and_invents_no_payoff():
    beat = StoryBeat(
        id="beat", scene_id="scene", start=0, end=2,
        narration="actor affects target", primary_asset_ids=["actor", "target"],
        action="REVEAL", asset_activations=[
            _activation("actor", "E1", 1, "LEADER"),
            _activation("target", "E1", 1, "PARTICIPANT"),
        ], event_authorities=[StoryEventAuthority(
            event_id="E1", leader_asset_ids=["actor"],
            participant_asset_ids=["target"],
        )],
    )
    relation = replace(_relation(), result_asset_id=None)
    flow, = SemanticEventFlowPlanner().compile(
        beat=beat, interactions=(relation,), transitions=(),
    )
    assert flow.steps[0].stage == EventFlowStage.ESTABLISH
    assert flow.steps[0].focus_asset_id == "actor"
    interaction = next(step for step in flow.steps if step.stage == EventFlowStage.INTERACT)
    assert (interaction.source_asset_id, interaction.target_asset_id) == ("actor", "target")
    assert EventFlowStage.PAYOFF not in flow.stages


def test_explicit_result_stays_in_own_event_and_unrelated_result_is_not_borrowed():
    beat = StoryBeat(
        id="beat", scene_id="scene", start=0, end=3,
        narration="actor target outcome; unrelated outcome", primary_asset_ids=["actor", "target", "result", "other"],
        action="REVEAL", asset_activations=[
            _activation("actor", "E1", 1, "LEADER"),
            _activation("target", "E1", 1, "PARTICIPANT"),
            _activation("result", "E1", 1, "RESULT"),
            _activation("other", "E2", 2, "RESULT"),
        ], event_authorities=[
            StoryEventAuthority(event_id="E1", sequence_order=1,
                                leader_asset_ids=["actor"], participant_asset_ids=["target"],
                                result_asset_ids=["result"]),
            StoryEventAuthority(event_id="E2", sequence_order=2, result_asset_ids=["other"]),
        ],
    )
    relation = replace(_relation(), result_asset_id="result")
    flows = SemanticEventFlowPlanner().compile(
        beat=beat, interactions=(relation,), transitions=(),
    )
    assert flows[0].result_asset_ids == ("result",)
    assert flows[1].result_asset_ids == ("other",)
    assert flows[0].steps.index(next(step for step in flows[0].steps if step.stage == EventFlowStage.INTERACT)) < flows[0].steps.index(next(step for step in flows[0].steps if step.stage == EventFlowStage.PAYOFF))


def test_dependency_handoff_preserves_event_order_and_story_window():
    beat = StoryBeat(
        id="beat", scene_id="scene", start=0, end=3,
        narration="actor then target", primary_asset_ids=["actor", "target"],
        action="REVEAL", asset_activations=[
            _activation("actor", "E1", 1, "LEADER"),
            _activation("target", "E2", 2, "LEADER"),
        ], event_authorities=[
            StoryEventAuthority(event_id="E1", sequence_order=1, leader_asset_ids=["actor"]),
            StoryEventAuthority(event_id="E2", sequence_order=2, leader_asset_ids=["target"], dependency_ids=["E1"]),
        ],
    )
    before = (beat.start, beat.end, [row.spoken_start for row in beat.asset_activations])
    flows = SemanticEventFlowPlanner().compile(beat=beat, interactions=(), transitions=())
    assert [flow.event_id for flow in flows] == ["E1", "E2"]
    assert flows[0].handoff_mode == "DEPENDENCY"
    assert flows[0].handoff_to_asset_ids == ("target",)
    assert (beat.start, beat.end, [row.spoken_start for row in beat.asset_activations]) == before


def test_multiple_participants_results_and_context_keep_distinct_roles():
    beat = StoryBeat(
        id="beat", scene_id="scene", start=0, end=2,
        narration="many", primary_asset_ids=["actor", "p1", "p2", "r1", "r2", "context"],
        action="REVEAL", asset_activations=[
            _activation(asset, "E1", 1, role) for asset, role in (
                ("actor", "LEADER"), ("p1", "PARTICIPANT"), ("p2", "PARTICIPANT"),
                ("r1", "RESULT"), ("r2", "RESULT"), ("context", "CONTEXT"),
            )
        ], event_authorities=[StoryEventAuthority(
            event_id="E1", leader_asset_ids=["actor"],
            participant_asset_ids=["p1", "p2"], result_asset_ids=["r1", "r2"],
            context_asset_ids=["context"],
        )],
    )
    flow, = SemanticEventFlowPlanner().compile(beat=beat, interactions=(), transitions=())
    assert flow.leader_asset_ids == ("actor",)
    assert flow.participant_asset_ids == ("p1", "p2")
    assert flow.result_asset_ids == ("r1", "r2")
    assert flow.context_asset_ids == ("context",)
    assert [step.focus_asset_id for step in flow.steps if step.stage == EventFlowStage.PAYOFF] == ["r1", "r2"]
    assert all(step.focus_asset_id != "context" for step in flow.steps)


def test_missing_source_and_ambiguous_source_authority_use_safe_fallback():
    beat = StoryBeat(
        id="beat", scene_id="scene", start=0, end=3,
        narration="target", primary_asset_ids=["target"], action="REVEAL",
        asset_activations=[_activation("target", "E1", 1, "LEADER")],
        event_authorities=[StoryEventAuthority(event_id="E1", leader_asset_ids=["target"])],
    )
    flow, = SemanticEventFlowPlanner().compile(beat=beat, interactions=(_relation(),), transitions=())
    assert EventFlowStage.INTERACT not in flow.stages

    beat.primary_asset_ids.append("actor")
    beat.asset_activations.extend([
        _activation("actor", "E1", 1, "LEADER"),
        _activation("actor", "E2", 2, "LEADER"),
    ])
    beat.event_authorities = [
        StoryEventAuthority(event_id="E1", leader_asset_ids=["target", "actor"]),
        StoryEventAuthority(event_id="E2", leader_asset_ids=["actor"]),
    ]
    flows = SemanticEventFlowPlanner().compile(beat=beat, interactions=(_relation(),), transitions=())
    assert sum(EventFlowStage.INTERACT in flow.stages for flow in flows) == 1
    assert flows[0].interactions[0].subject_asset_id == "actor"


def test_missing_result_carrier_invents_no_payoff():
    beat = StoryBeat(
        id="beat", scene_id="scene", start=0, end=2,
        narration="actor target", primary_asset_ids=["actor", "target"],
        action="REVEAL", asset_activations=[
            _activation("actor", "E1", 1, "LEADER"),
            _activation("target", "E1", 1, "PARTICIPANT"),
        ], event_authorities=[StoryEventAuthority(
            event_id="E1", leader_asset_ids=["actor"], participant_asset_ids=["target"],
        )],
    )
    relation = replace(_relation(), result_asset_id="ghost")
    flow, = SemanticEventFlowPlanner().compile(beat=beat, interactions=(relation,), transitions=())
    assert EventFlowStage.PAYOFF not in flow.stages


def test_no_structured_relation_preserves_establish_and_add():
    beat = StoryBeat(
        id="beat", scene_id="scene", start=0, end=2,
        narration="generic", primary_asset_ids=["actor", "target"],
        action="FOCUS", asset_activations=[
            _activation("actor", "E1", 1, "LEADER"),
            _activation("target", "E1", 1, "PARTICIPANT"),
        ],
    )
    flow, = SemanticEventFlowPlanner().compile(beat=beat, interactions=(), transitions=())
    assert flow.stages == (EventFlowStage.ESTABLISH, EventFlowStage.ADD, EventFlowStage.RELEASE)


def test_compound_carrier_remains_one_semantic_establish_step():
    left = _activation("actor-left", "E1", 1, "LEADER")
    right = _activation("actor-right", "E1", 1, "LEADER")
    left.semantic_unit_id = right.semantic_unit_id = "compound-actor"
    beat = StoryBeat(
        id="beat", scene_id="scene", start=0, end=2,
        narration="compound actor", primary_asset_ids=["actor-left", "actor-right"],
        action="FOCUS", asset_activations=[left, right],
        event_authorities=[StoryEventAuthority(
            event_id="E1", leader_asset_ids=["actor-left", "actor-right"],
        )],
    )
    flow, = SemanticEventFlowPlanner().compile(beat=beat, interactions=(), transitions=())
    establish = [step for step in flow.steps if step.stage == EventFlowStage.ESTABLISH]
    assert len(establish) == 1
    assert establish[0].participant_asset_ids == ("actor-left", "actor-right")


def test_specification_without_executable_relation_has_no_causal_phase():
    beat = StoryBeat(
        id="beat", scene_id="scene", start=0, end=2,
        narration="actor specifies target", primary_asset_ids=["actor", "target"],
        action="FOCUS", asset_activations=[
            _activation("actor", "E1", 1, "LEADER"),
            _activation("target", "E1", 1, "PARTICIPANT"),
        ], event_authorities=[StoryEventAuthority(
            event_id="E1", leader_asset_ids=["actor"],
            participant_asset_ids=["target"], relation_kinds=["SPECIFIES"],
        )],
    )
    relation = replace(_relation("SPECIFIES"), executable=False, result_asset_id=None)
    flow, = SemanticEventFlowPlanner().compile(
        beat=beat, interactions=(relation,), transitions=(),
    )
    assert EventFlowStage.INTERACT not in flow.stages
    assert EventFlowStage.PAYOFF not in flow.stages


def test_typed_event_roles_and_order_override_conflicting_activation_hints():
    beat = StoryBeat(
        id="beat", scene_id="scene", start=0, end=3,
        narration="typed authority", primary_asset_ids=["actor", "target", "later"],
        action="FOCUS", asset_activations=[
            _activation("actor", "E1", 2, "LEADER"),
            _activation("target", "E1", 2, "PARTICIPANT"),
            _activation("later", "E2", 1, "LEADER"),
        ], event_authorities=[
            StoryEventAuthority(event_id="E1", sequence_order=1,
                                leader_asset_ids=["target"], participant_asset_ids=["actor"]),
            StoryEventAuthority(event_id="E2", sequence_order=2,
                                leader_asset_ids=[]),
        ],
    )
    flows = SemanticEventFlowPlanner().compile(beat=beat, interactions=(), transitions=())
    assert [flow.event_id for flow in flows] == ["E1", "E2"]
    assert flows[0].leader_asset_ids == ("target",)
    assert flows[0].participant_asset_ids == ("actor",)
    assert flows[0].steps[0].focus_asset_id == "target"
    assert flows[1].leader_asset_ids == ()
    assert EventFlowStage.ESTABLISH not in flows[1].stages
