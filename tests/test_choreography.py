from pathlib import Path

from app.choreography import ChoreographyDirector, HookKind, SequencePhase
from app.models import PackageModel, SceneSource, StoryBeat, VisualAsset


def _scene(scene_id: str, semantic_name: str, concept: str = "") -> SceneSource:
    return SceneSource(
        id=scene_id,
        image_path=Path(f"/{scene_id}.png"),
        order=int(scene_id.split("-")[-1]),
        visual_concept=concept,
        relation_to_previous="CONTINUES_CANONICAL_EXPLANATION",
        units=[
            {
                "unit_id": "UNIT_001",
                "semantic_name": semantic_name,
                "narrative_function": f"EXPLAIN_{semantic_name.upper()}",
                "semantic_intent": "EXPLAIN",
            }
        ],
    )


def _beat(index: int, narration: str) -> StoryBeat:
    start = (index - 1) * 2.4
    return StoryBeat(
        id=f"beat-{index:03d}",
        scene_id=f"scene-{index}",
        start=start,
        end=start + 2.4,
        audio_start=start + 0.2,
        audio_end=start + 2.1,
        narration=narration,
        primary_asset_ids=[f"asset-{index}"],
        support_asset_ids=[f"support-{index}"],
        action="REVEAL_DETAIL",
    )


def test_choreography_groups_story_and_schedules_multiple_hooks_without_scene_ids() -> None:
    semantics = [
        "wallet_model",
        "total_balance",
        "reserved_funds",
        "online_spending_cap",
        "payment_request",
        "subsequent_decline",
        "website_decline",
        "payment_route",
        "privacy_shield",
        "ten_retries",
        "actual_available_amount",
        "load_exceeds_gate_limit",
    ]
    scenes = [_scene(f"scene-{i}", semantic) for i, semantic in enumerate(semantics, start=1)]
    package = PackageModel(root=Path("/tmp"), package_id="p", scenes=scenes, script="x")
    beats = [_beat(i, semantic.replace("_", " ")) for i, semantic in enumerate(semantics, start=1)]

    plan = ChoreographyDirector().plan(package, beats, [])

    assert len(plan.directives) == len(beats)
    assert plan.directives[0].hook == HookKind.OPEN
    assert len(plan.hook_beats()) >= 3
    assert all(2 <= len(sequence.beat_ids) <= 4 for sequence in plan.sequences)
    assert any(row.action == "REJECT" for row in plan.directives)
    assert any(row.action == "BLOCK" for row in plan.directives)
    assert any(row.action == "LOOP" for row in plan.directives)
    assert any(row.phase == SequencePhase.CONSEQUENCE for row in plan.directives)


def test_choreography_uses_semantic_metadata_instead_of_specific_scene_number() -> None:
    package = PackageModel(
        root=Path("/tmp"),
        package_id="p",
        scenes=[_scene("scene-77", "subsequent_decline")],
        script="x",
    )
    beat = StoryBeat(
        id="arbitrary-beat",
        scene_id="scene-77",
        start=0.0,
        end=2.0,
        audio_start=0.1,
        audio_end=1.8,
        narration="neutral narration",
        primary_asset_ids=["a"],
        support_asset_ids=["b"],
        action="REVEAL_DETAIL",
    )
    plan = ChoreographyDirector().plan(package, [beat], [])
    assert plan.directives[0].action == "REJECT"
    assert plan.directives[0].tension >= 0.9


def test_hook_mechanisms_vary_across_long_story() -> None:
    semantics = [
        "wallet_model", "reserved_funds", "online_spending_cap", "payment_request",
        "subsequent_decline", "ten_retries", "physical_store_compare", "privacy_shield",
        "actual_available_amount", "load_exceeds_gate_limit", "subsequent_decline", "solution_raise_limit",
    ]
    scenes = [_scene(f"scene-{i}", semantic) for i, semantic in enumerate(semantics, start=1)]
    package = PackageModel(root=Path("/tmp"), package_id="p", scenes=scenes, script="x")
    beats = [_beat(i, semantic.replace("_", " ")) for i, semantic in enumerate(semantics, start=1)]

    plan = ChoreographyDirector().plan(package, beats, [])
    hooked = [sequence for sequence in plan.sequences if sequence.hook != HookKind.NONE]

    assert len(hooked) >= 3
    mechanisms = [sequence.hook_mechanism.value for sequence in hooked]
    assert len(set(mechanisms)) >= 2
    assert mechanisms[0] in {"CURIOSITY", "CONTRADICTION"}


def test_choreography_marks_cross_asset_focus_as_semantic_handoff() -> None:
    from app.choreography import ContinuityMode

    package = PackageModel(
        root=Path("/tmp"), package_id="p",
        scenes=[_scene("scene-1", "wallet_model"), _scene("scene-2", "payment_request")],
        script="x",
    )
    first = _beat(1, "wallet")
    second = _beat(2, "request")
    plan = ChoreographyDirector().plan(package, [first, second], [])

    assert plan.directives[1].continuity_from == first.primary_asset_ids[0]
    assert plan.directives[1].continuity_mode == ContinuityMode.SEMANTIC_HANDOFF


def test_choreography_binds_concept_cutout_instead_of_tall_character() -> None:
    scene = SceneSource(
        id="scene-1",
        image_path=Path("/scene.png"),
        order=1,
        units=[
            {
                "unit_id": "UNIT_001",
                "semantic_name": "wallet_model",
                "type": "GROUP",
                "role": "PRIMARY",
            },
            {
                "unit_id": "UNIT_002",
                "semantic_name": "adult_secondary_customer",
                "type": "SECONDARY_CHARACTER",
                "role": "SUPPORTING",
            },
        ],
    )
    package = PackageModel(root=Path("/tmp"), package_id="p", scenes=[scene], script="x")
    beat = StoryBeat(
        id="beat-001",
        scene_id="scene-1",
        start=0.0,
        end=2.0,
        audio_start=0.2,
        audio_end=1.8,
        narration="wallet",
        primary_asset_ids=["character"],
        support_asset_ids=["wallet"],
        action="REVEAL_DETAIL",
    )
    assets = [
        VisualAsset(
            id="character", scene_id="scene-1", role="primary_visual",
            image_path=Path("/character.png"), extraction_method="test",
            source_bbox=(20, 20, 280, 760), source_canvas_width=1000, source_canvas_height=1000,
            source_area_ratio=0.21,
        ),
        VisualAsset(
            id="wallet", scene_id="scene-1", role="support_visual_1",
            image_path=Path("/wallet.png"), extraction_method="test",
            source_bbox=(420, 250, 460, 360), source_canvas_width=1000, source_canvas_height=1000,
            source_area_ratio=0.17,
        ),
    ]

    directive = ChoreographyDirector().plan(package, [beat], assets).directives[0]

    assert directive.primary_asset_id == "wallet"
    assert directive.actor_asset_ids == ("character",)
    assert directive.interaction_asset_id == "character"


def test_story_primary_keeps_narration_locked_timing_when_choreography_focus_is_support() -> None:
    """Semantic focus may change without letting authored primary artwork arrive late."""
    from app.choreography import ChoreographyDirective, ChoreographyPlan, HookKind, SequencePhase
    from app.models import CompositionBeat, LayoutItem
    from app.motion import MotionPlanner

    beat = StoryBeat(
        id="beat-001",
        scene_id="SCENE_GENERIC",
        start=0.0,
        end=1.8,
        audio_start=0.30,
        audio_end=1.50,
        narration="payment rejected",
        primary_asset_ids=["authored-primary"],
        support_asset_ids=["semantic-focus"],
        action="REVEAL_DETAIL",
    )
    plan = ChoreographyPlan(directives=(ChoreographyDirective(
        beat_id=beat.id,
        sequence_id="sequence-001",
        phase=SequencePhase.ACTION,
        action="REJECT",
        hook=HookKind.OPEN,
        primary_asset_id="semantic-focus",
        support_asset_ids=("authored-primary",),
        energy=0.9,
        tension=0.9,
    ),))
    composition = [CompositionBeat(beat_id=beat.id, items=[
        LayoutItem(asset_id="authored-primary", x=0.30, y=0.5, width=0.38, height=0.50),
        LayoutItem(asset_id="semantic-focus", x=0.70, y=0.5, width=0.26, height=0.28),
    ])]

    cues = MotionPlanner().plan([beat], composition, plan)
    by_asset = {cue.asset_id: cue for cue in cues}
    authored = by_asset["authored-primary"]
    semantic = by_asset["semantic-focus"]

    assert authored.params["semantic_settle_time"] <= beat.audio_start + 0.12
    assert semantic.params["semantic_settle_time"] <= beat.audio_start + 0.12
    assert semantic.params["program"]["name"] != authored.params["program"]["name"]



def test_two_beat_handoff_counts_as_progressive_visual_addition() -> None:
    package = PackageModel(
        root=Path("/tmp"),
        package_id="generic-two-beat",
        scenes=[
            _scene("scene-1", "plain_alpha"),
            _scene("scene-2", "plain_beta"),
        ],
        script="x",
    )
    beats = [_beat(1, "plain alpha"), _beat(2, "plain beta")]

    plan = ChoreographyDirector().plan(package, beats, [])

    assert len(plan.sequences) == 1
    assert plan.directives[1].phase == SequencePhase.HANDOFF
    stages = {stage.value for stage in plan.sequences[0].grammar_stages}
    assert {"ENTER", "READ", "ADD", "RELEASE"} <= stages


def test_semantic_event_flow_compiles_final_package_roles_into_visual_mini_story() -> None:
    from app.choreography import (
        EventFlowStage,
        InteractionIntent,
        SemanticEventFlowPlanner,
        VisualStateTransition,
    )
    from app.models import AssetActivation

    beat = StoryBeat(
        id="beat-events",
        scene_id="scene-1",
        start=0.0,
        end=2.0,
        audio_start=0.0,
        audio_end=2.0,
        narration="alpha beta gamma",
        primary_asset_ids=["leader"],
        support_asset_ids=["participant", "context", "result"],
        action="REVEAL_DETAIL",
        asset_activations=[
            AssetActivation(
                asset_id="leader",
                semantic_event_id="E1",
                semantic_event_order=1,
                semantic_event_roles=["LEADER", "TEXT_ANCHOR"],
                source="final_package_semantic_binding",
                policy="EXPLICIT",
                spoken_start=0.1,
                spoken_end=0.5,
                confidence=0.99,
            ),
            AssetActivation(
                asset_id="participant",
                semantic_event_id="E1",
                semantic_event_order=1,
                semantic_event_roles=["PARTICIPANT"],
                source="final_package_semantic_binding",
                policy="EXPLICIT",
                spoken_start=0.2,
                spoken_end=0.6,
                confidence=0.96,
            ),
            AssetActivation(
                asset_id="context",
                semantic_event_id="E1",
                semantic_event_order=1,
                semantic_event_roles=["CONTEXT"],
                source="final_package_semantic_binding",
                policy="SEMANTIC",
                spoken_start=0.1,
                spoken_end=0.6,
                confidence=0.90,
            ),
            AssetActivation(
                asset_id="result",
                semantic_event_id="E2",
                semantic_event_order=2,
                semantic_event_roles=["LEADER", "RESULT", "TEXT_ANCHOR"],
                semantic_event_dependency_ids=["E1"],
                source="final_package_semantic_binding",
                policy="EXPLICIT",
                spoken_start=0.9,
                spoken_end=1.3,
                confidence=0.99,
            ),
        ],
    )
    relation = InteractionIntent(
        semantic_action="REVEAL",
        relationship="CAUSES",
        subject_asset_id="leader",
        object_asset_id="participant",
        result_asset_id="result",
        authority="FINAL_PACKAGE_ASSET_RELATION",
        confidence=0.98,
        executable=True,
        requires_state_change=True,
    )
    transitions = (
        VisualStateTransition(
            asset_id="participant",
            from_state="CONTEXT",
            to_state="EVIDENCE",
            reason="CAUSES",
            meaningful=True,
        ),
        VisualStateTransition(
            asset_id="result",
            from_state="PENDING",
            to_state="RESULT",
            reason="RESULT",
            meaningful=True,
        ),
    )

    flows = SemanticEventFlowPlanner().compile(
        beat=beat,
        interactions=(relation,),
        transitions=transitions,
    )

    assert [flow.event_id for flow in flows] == ["E1", "E2"]
    assert flows[0].leader_asset_ids == ("leader",)
    assert flows[0].participant_asset_ids == ("participant",)
    assert flows[0].context_asset_ids == ("context",)
    assert flows[0].text_anchor_asset_ids == ("leader",)
    assert flows[0].interactions == (relation,)
    assert flows[0].stages == (
        EventFlowStage.ESTABLISH,
        EventFlowStage.ADD,
        EventFlowStage.INTERACT,
        EventFlowStage.REACT,
        EventFlowStage.RELEASE,
    )
    assert flows[1].dependency_ids == ("E1",)
    assert flows[1].leader_asset_ids == ("result",)
    assert flows[1].result_asset_ids == ("result",)
    assert flows[1].stages == (
        EventFlowStage.ESTABLISH,
        EventFlowStage.PAYOFF,
        EventFlowStage.RELEASE,
    )
    assert [step.stage for step in flows[0].steps] == [
        EventFlowStage.ESTABLISH,
        EventFlowStage.ADD,
        EventFlowStage.INTERACT,
        EventFlowStage.REACT,
        EventFlowStage.RELEASE,
    ]
    assert flows[0].steps[0].focus_asset_id == "leader"
    assert flows[0].steps[1].focus_asset_id == "participant"
    assert flows[0].steps[2].source_asset_id == "leader"
    assert flows[0].steps[2].target_asset_id == "participant"
    assert flows[0].steps[2].relationship == "CAUSES"
    assert flows[0].steps[3].focus_asset_id == "participant"
    assert flows[0].handoff_to_event_id == "E2"
    assert flows[0].handoff_to_asset_id == "result"
    assert flows[0].steps[-1].focus_asset_id == "result"
    assert "context" not in flows[0].focus_path_asset_ids
    assert flows[1].steps[1].stage == EventFlowStage.PAYOFF
    assert flows[1].steps[1].focus_asset_id == "result"
    assert flows[1].handoff_to_event_id is None


def test_event_flow_preserves_every_participant_and_every_result_as_distinct_focus_steps() -> None:
    from app.choreography import EventFlowStage, SemanticEventFlowPlanner
    from app.models import AssetActivation

    def row(asset_id: str, role: str, start: float, order: int) -> AssetActivation:
        return AssetActivation(
            asset_id=asset_id,
            semantic_unit_id=asset_id,
            semantic_event_id="E1",
            semantic_event_order=1,
            semantic_event_roles=[role],
            sequence_order=order,
            source="final_package_semantic_binding",
            policy="EXPLICIT",
            spoken_start=start,
            spoken_end=start + 0.2,
            confidence=0.99,
        )

    beat = StoryBeat(
        id="multi",
        scene_id="scene-1",
        start=0.0,
        end=2.0,
        audio_start=0.0,
        audio_end=1.8,
        narration="leader p1 p2 r1 r2",
        primary_asset_ids=["leader"],
        support_asset_ids=["p1", "p2", "r1", "r2"],
        action="EXPLAIN",
        asset_activations=[
            row("leader", "LEADER", 0.1, 1),
            row("p1", "PARTICIPANT", 0.3, 2),
            row("p2", "PARTICIPANT", 0.5, 3),
            row("r1", "RESULT", 0.9, 4),
            row("r2", "RESULT", 1.1, 5),
        ],
    )

    flow = SemanticEventFlowPlanner().compile(
        beat=beat, interactions=(), transitions=()
    )[0]

    assert [
        (step.stage, step.focus_asset_id)
        for step in flow.steps
        if step.stage != EventFlowStage.RELEASE
    ] == [
        (EventFlowStage.ESTABLISH, "leader"),
        (EventFlowStage.ADD, "p1"),
        (EventFlowStage.ADD, "p2"),
        (EventFlowStage.PAYOFF, "r1"),
        (EventFlowStage.PAYOFF, "r2"),
    ]
    assert flow.focus_path_asset_ids == ("leader", "p1", "p2", "r1", "r2")


def test_event_flow_dependency_graph_branches_without_fake_serial_handoff() -> None:
    from app.choreography import SemanticEventFlowPlanner
    from app.models import AssetActivation

    def row(asset_id: str, event_id: str, event_order: int, deps: list[str]) -> AssetActivation:
        return AssetActivation(
            asset_id=asset_id,
            semantic_unit_id=asset_id,
            semantic_event_id=event_id,
            semantic_event_order=event_order,
            semantic_event_roles=["LEADER"],
            semantic_event_dependency_ids=deps,
            source="final_package_semantic_binding",
            policy="EXPLICIT",
            spoken_start=0.1 * event_order,
            spoken_end=0.1 * event_order + 0.2,
            confidence=0.99,
        )

    beat = StoryBeat(
        id="branch",
        scene_id="scene-1",
        start=0.0,
        end=1.5,
        audio_start=0.0,
        audio_end=1.4,
        narration="root branch one branch two",
        primary_asset_ids=["root"],
        support_asset_ids=["left", "right"],
        action="EXPLAIN",
        asset_activations=[
            row("root", "E1", 1, []),
            row("left", "E2", 2, ["E1"]),
            row("right", "E3", 3, ["E1"]),
        ],
    )

    flows = SemanticEventFlowPlanner().compile(
        beat=beat, interactions=(), transitions=()
    )
    root = flows[0]
    assert root.handoff_mode == "BRANCH"
    assert root.handoff_to_event_ids == ("E2", "E3")
    assert root.handoff_to_asset_ids == ("left", "right")
    assert root.handoff_to_event_id is None
    assert root.handoff_to_asset_id is None
    assert root.steps[-1].focus_asset_id is None
    assert root.steps[-1].participant_asset_ids == ("left", "right")


def test_compare_event_is_relational_but_not_mislabeled_as_cause_effect() -> None:
    from app.choreography import (
        ChoreographyPattern,
        EventFlowStage,
        InteractionIntent,
        SemanticEventFlowPlanner,
    )
    from app.models import AssetActivation

    rows = [
        AssetActivation(
            asset_id="left",
            semantic_unit_id="left",
            semantic_event_id="E1",
            semantic_event_order=1,
            semantic_event_roles=["LEADER"],
            source="final_package_semantic_binding",
            policy="EXPLICIT",
            spoken_start=0.1,
            spoken_end=0.6,
            confidence=0.99,
        ),
        AssetActivation(
            asset_id="right",
            semantic_unit_id="right",
            semantic_event_id="E1",
            semantic_event_order=1,
            semantic_event_roles=["PARTICIPANT"],
            source="final_package_semantic_binding",
            policy="EXPLICIT",
            spoken_start=0.2,
            spoken_end=0.6,
            confidence=0.99,
        ),
    ]
    beat = StoryBeat(
        id="compare",
        scene_id="scene-1",
        start=0.0,
        end=1.0,
        narration="left versus right",
        primary_asset_ids=["left"],
        support_asset_ids=["right"],
        action="COMPARE",
        asset_activations=rows,
    )
    relation = InteractionIntent(
        semantic_action="COMPARE",
        relationship="PARALLEL_CAUSES",
        subject_asset_id="left",
        object_asset_id="right",
        authority="FINAL_PACKAGE_ASSET_RELATION",
        confidence=0.99,
        executable=True,
        requires_state_change=True,
    )
    flows = SemanticEventFlowPlanner().compile(
        beat=beat, interactions=(relation,), transitions=()
    )

    assert EventFlowStage.INTERACT in flows[0].stages
    assert EventFlowStage.REACT not in flows[0].stages
    assert ChoreographyDirector._pattern_for(
        beat, (relation,), (), flows
    ) == ChoreographyPattern.PROGRESSIVE_BUILD



def test_event_flow_completes_executable_relation_without_redundant_state_or_result_roles() -> None:
    """Gray-Hat regression: relation authority alone must complete REACT + PAYOFF."""
    from app.choreography import EventFlowStage, InteractionIntent, SemanticEventFlowPlanner
    from app.models import AssetActivation

    def row(asset_id: str, role: str, start: float) -> AssetActivation:
        return AssetActivation(
            asset_id=asset_id,
            semantic_unit_id=asset_id,
            semantic_event_id="E1",
            semantic_event_order=1,
            semantic_event_roles=[role],
            source="final_package_semantic_binding",
            policy="EXPLICIT",
            spoken_start=start,
            spoken_end=start + 0.35,
            confidence=0.99,
        )

    beat = StoryBeat(
        id="gray-relation",
        scene_id="scene-gray",
        start=0.0,
        end=2.0,
        audio_start=0.0,
        audio_end=1.9,
        narration="source discovers target and produces result",
        primary_asset_ids=["source"],
        support_asset_ids=["target", "result"],
        action="EXPLAIN",
        asset_activations=[
            row("source", "LEADER", 0.10),
            row("target", "PARTICIPANT", 0.55),
            # Intentionally not RESULT: the explicit relation result is the authority.
            row("result", "PARTICIPANT", 1.05),
        ],
    )
    relation = InteractionIntent(
        semantic_action="EXPLAIN",
        relationship="DISCOVERS",
        subject_asset_id="source",
        object_asset_id="target",
        result_asset_id="result",
        authority="FINAL_PACKAGE_ASSET_RELATION",
        confidence=0.99,
        executable=True,
        # Intentionally false: visual relation completeness must not depend on this
        # redundant flag when the Final Package already authored a distinct target.
        requires_state_change=False,
    )

    flows = SemanticEventFlowPlanner().compile(
        beat=beat,
        interactions=(relation,),
        transitions=(),
    )

    assert len(flows) == 1
    flow = flows[0]
    assert EventFlowStage.INTERACT in flow.stages
    assert EventFlowStage.REACT in flow.stages
    assert EventFlowStage.PAYOFF in flow.stages
    assert "result" in flow.result_asset_ids
    assert any(
        step.stage == EventFlowStage.REACT and step.target_asset_id == "target"
        for step in flow.steps
    )
    assert any(
        step.stage == EventFlowStage.PAYOFF and step.result_asset_id == "result"
        for step in flow.steps
    )


def test_relation_result_payoff_stays_with_result_story_event_without_result_role() -> None:
    """Explicit relation result must pay off in its Story-owned event, not steal timing."""
    from app.choreography import EventFlowStage, InteractionIntent, SemanticEventFlowPlanner
    from app.models import AssetActivation

    def row(
        asset_id: str,
        *,
        event_id: str,
        order: int,
        role: str,
        start: float,
    ) -> AssetActivation:
        return AssetActivation(
            asset_id=asset_id,
            semantic_unit_id=asset_id,
            semantic_event_id=event_id,
            semantic_event_order=order,
            semantic_event_roles=[role],
            source="final_package_semantic_binding",
            policy="EXPLICIT",
            spoken_start=start,
            spoken_end=start + 0.30,
            confidence=0.99,
        )

    beat = StoryBeat(
        id="gray-cross-event-result",
        scene_id="scene-gray",
        start=0.0,
        end=2.2,
        audio_start=0.0,
        audio_end=2.0,
        narration="source acts on target then result appears",
        primary_asset_ids=["source"],
        support_asset_ids=["target", "result"],
        action="EXPLAIN",
        asset_activations=[
            row("source", event_id="E1", order=1, role="LEADER", start=0.10),
            row("target", event_id="E1", order=1, role="PARTICIPANT", start=0.50),
            # The result belongs to E2 but is intentionally only a LEADER there.
            row("result", event_id="E2", order=2, role="LEADER", start=1.20),
        ],
    )
    relation = InteractionIntent(
        semantic_action="RESOLVE",
        relationship="REPAIRS",
        subject_asset_id="source",
        object_asset_id="target",
        result_asset_id="result",
        authority="FINAL_PACKAGE_ASSET_RELATION",
        confidence=0.99,
        executable=True,
        requires_state_change=True,
    )

    flows = SemanticEventFlowPlanner().compile(
        beat=beat,
        interactions=(relation,),
        transitions=(),
    )

    by_id = {flow.event_id: flow for flow in flows}
    assert "result" not in by_id["E1"].result_asset_ids
    assert "result" in by_id["E2"].result_asset_ids
    payoff = next(
        step for step in by_id["E2"].steps
        if step.stage == EventFlowStage.PAYOFF and step.result_asset_id == "result"
    )
    assert payoff.relationship == "REPAIRS"
    assert payoff.semantic_action == "RESOLVE"
