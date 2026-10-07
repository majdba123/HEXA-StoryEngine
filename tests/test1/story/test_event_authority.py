from pathlib import Path

from app.canonical import (
    CanonicalAsset, CanonicalProgression, CanonicalRelation, CanonicalScene,
    CanonicalSemanticEvent,
)
from app.models import AssetActivation, SemanticEventProxy, StoryBeat, StorySemanticContext
from app.choreography.actions import SemanticActionResolver
from app.story.event_authority import event_authority


def _asset(asset_id: str, event_id: str, **kw) -> CanonicalAsset:
    return CanonicalAsset(
        unit_id=asset_id, asset_id=asset_id, scene_id="S", semantic_event_id=event_id,
        **kw,
    )


def _scene(*events: CanonicalSemanticEvent, assets=(), relations=(), order=()) -> CanonicalScene:
    return CanonicalScene(
        id="S", image_path=Path("unused.png"), order=0,
        units=tuple(assets), semantic_events=tuple(events), relations=tuple(relations),
        semantic_progression=(CanonicalProgression(event_order=tuple(order)) if order else None),
    )


def _event(event_id: str, index: int, leader: str | None = None, **kw) -> CanonicalSemanticEvent:
    return CanonicalSemanticEvent(
        semantic_event_id=event_id, scene_id="S", sequence_order=index,
        visual_leader_asset_id=leader, **kw,
    )


def _beat(*rows: AssetActivation) -> StoryBeat:
    return StoryBeat(
        id="B", scene_id="S", start=0, end=3, narration="result then cause",
        action="EXPLAIN", primary_asset_ids=[row.asset_id for row in rows],
        asset_activations=list(rows),
    )


def _row(asset_id: str, event_id: str, start: float = 0.0, **kw) -> AssetActivation:
    policy = kw.pop("policy", "EXPLICIT")
    return AssetActivation(
        asset_id=asset_id, semantic_unit_id=asset_id, semantic_event_id=event_id,
        spoken_start=start, spoken_end=start + 0.5,
        policy=policy, source="unified_final_package", **kw,
    )


def test_two_events_keep_distinct_leaders_and_windows() -> None:
    scene = _scene(_event("A", 1, "actor_a"), _event("B", 2, "actor_b"))
    records, diagnostics = event_authority(scene, _beat(_row("actor_a", "A", 0), _row("actor_b", "B", 2)))
    assert [row.leader_asset_ids for row in records] == [["actor_a"], ["actor_b"]]
    assert [row.spoken_start for row in records] == [0, 2]
    assert diagnostics == []


def test_actor_target_result_and_misleading_names_use_typed_ids() -> None:
    scene = _scene(
        _event("A", 1, "actor", participant_asset_ids=("target",), result_asset_ids=("result",)),
        assets=[_asset("actor", "A", semantic_name="result"),
                _asset("target", "A", semantic_name="attacker"),
                _asset("result", "A", semantic_name="context")],
        relations=[CanonicalRelation(subject_asset_id="actor", object_asset_id="target",
                                     result_asset_id="result", relation_type="CAUSES")],
    )
    records, _ = event_authority(scene, _beat(*(_row(name, "A") for name in ("actor", "target", "result"))))
    assert records[0].leader_asset_ids == ["actor"]
    assert records[0].participant_asset_ids == ["target"]
    assert records[0].result_asset_ids == ["result"]
    assert records[0].relation_kinds == ["CAUSES"]


def test_result_first_narration_does_not_change_causal_direction_or_dependency() -> None:
    scene = _scene(
        _event("RESULT", 1, "result", result_asset_ids=("result",)),
        _event("SOURCE", 2, "source"),
        relations=[CanonicalRelation(subject_asset_id="source", object_asset_id="result",
                                     relation_type="LEADS_TO")],
    )
    records, _ = event_authority(scene, _beat(_row("result", "RESULT", 0), _row("source", "SOURCE", 2)))
    assert [row.event_id for row in records] == ["RESULT", "SOURCE"]
    assert records[0].dependency_ids == records[1].dependency_ids == []
    assert records[0].spoken_start < records[1].spoken_start
    assert records[0].relation_kinds == records[1].relation_kinds == []


def test_comparison_relation_is_preserved_without_causal_result() -> None:
    scene = _scene(
        _event("A", 1, "a", participant_asset_ids=("b",)),
        relations=[CanonicalRelation(subject_asset_id="a", object_asset_id="b",
                                     relation_type="PARALLEL_CAUSES")],
    )
    records, _ = event_authority(scene, _beat(_row("a", "A"), _row("b", "A")))
    assert records[0].relation_kinds == ["PARALLEL_CAUSES"]
    assert records[0].result_asset_ids == []


def test_dependency_and_authored_order_are_retained_without_rescheduling() -> None:
    scene = _scene(_event("A", 1, "a"), _event("B", 2, "b", depends_on_event_ids=("A",)))
    records, _ = event_authority(scene, _beat(_row("a", "A", 1), _row("b", "B", 0)))
    assert [row.sequence_order for row in records] == [1, 2]
    assert records[1].dependency_ids == ["A"]
    assert records[1].spoken_start == 0


def test_group_policy_carried_by_activation_is_unchanged() -> None:
    row = _row("a", "A", group_animation_policy="SEQUENTIAL_WITHIN_PHRASE")
    event_authority(_scene(_event("A", 1, "a")), _beat(row))
    assert row.group_animation_policy == "SEQUENTIAL_WITHIN_PHRASE"


def test_cross_ontology_roles_are_not_false_conflicts() -> None:
    scene = _scene(_event("A", 1, "a"), assets=[_asset("a", "A", role="primary", semantic_role="CHARACTER")])
    _, diagnostics = event_authority(scene, _beat(_row("a", "A")))
    assert not any(row.conflict_type == "ROLE_CONFLICT" for row in diagnostics)


def test_genuine_role_conflict_preserves_both_values() -> None:
    scene = _scene(_event("A", 1, "a"), assets=[_asset("a", "A", role="supporting", semantic_role="PRIMARY")])
    _, diagnostics = event_authority(scene, _beat(_row("a", "A")))
    conflict = next(row for row in diagnostics if row.conflict_type == "ROLE_CONFLICT")
    assert conflict.source_values == {"role": "supporting", "semantic_role": "PRIMARY"}


def test_proven_event_leader_precedes_object_primary_visual_focus() -> None:
    scene = _scene(
        _event("A", 1, "leader", participant_asset_ids=("focus",)),
        assets=[_asset("leader", "A", visual_focus="SUPPORT"),
                _asset("focus", "A", visual_focus="PRIMARY")],
    )
    records, diagnostics = event_authority(
        scene, _beat(_row("leader", "A"), _row("focus", "A")),
    )
    assert records[0].leader_asset_ids == ["leader"]
    assert [row.conflict_type for row in diagnostics] == ["LEADER_VISUAL_FOCUS_CONFLICT"]


def test_progression_mismatch_is_diagnostic_only() -> None:
    scene = _scene(_event("A", 1, "a"), _event("B", 2, "b"), order=("B", "A"))
    records, diagnostics = event_authority(scene, _beat(_row("a", "A"), _row("b", "B")))
    assert [row.sequence_order for row in records] == [1, 2]
    assert [row.conflict_type for row in diagnostics] == ["PROGRESSION_ORDER_CONFLICT"]


def test_review_flag_and_low_confidence_do_not_suppress_valid_carrier() -> None:
    scene = _scene(_event("A", 1, "a", needs_review=True, confidence=0.2),
                   assets=[_asset("a", "A", needs_review=True, confidence=0.3)])
    records, diagnostics = event_authority(scene, _beat(_row("a", "A")))
    assert records[0].leader_asset_ids == ["a"]
    assert {row.conflict_type for row in diagnostics} == {"ASSET_REVIEW", "EVENT_REVIEW"}


def test_event_result_outranks_unrelated_inferred_result() -> None:
    scene = _scene(_event("A", 1, "a", result_asset_ids=("real",)))
    beat = _beat(_row("a", "A"), _row("real", "A"))
    beat.semantic_context = StorySemanticContext(result_unit_ids=["real", "misleading"])
    records, diagnostics = event_authority(scene, beat)
    assert records[0].result_asset_ids == ["real"]
    assert diagnostics[0].conflict_type == "EVENT_INFERRED_RESULT_CONFLICT"
    assert diagnostics[0].asset_ids == ["real", "misleading"]


def test_multiple_results_keep_only_proven_event_carriers() -> None:
    scene = _scene(_event("A", 1, "a", result_asset_ids=("r1", "r2")))
    records, _ = event_authority(scene, _beat(_row("a", "A"), _row("r1", "A")))
    assert records[0].result_asset_ids == ["r1"]


def test_compound_proxy_is_a_proven_event_carrier_without_new_cutout() -> None:
    scene = _scene(_event("A", 1, "child"))
    beat = _beat()
    beat.semantic_event_proxies = [SemanticEventProxy(
        asset_id="parent", semantic_unit_id="child", semantic_event_id="A",
        trigger_text="child", trigger_char_start=0, trigger_char_end=5,
        spoken_start=0.2, spoken_end=0.5, reveal_start=0.2,
        semantic_peak=0.4, settle_at=0.5,
    )]
    records, _ = event_authority(scene, beat)
    assert records[0].leader_asset_ids == ["parent"]


def test_missing_carrier_abstains_without_substitution() -> None:
    scene = _scene(_event("A", 1, "missing", result_asset_ids=("also_missing",)))
    records, diagnostics = event_authority(scene, _beat(_row("other", "A")))
    assert records[0].leader_asset_ids == records[0].result_asset_ids == []
    assert {row.conflict_type for row in diagnostics} == {
        "UNPROVEN_LEADER_CARRIER", "UNPROVEN_RESULT_CARRIER"
    }
    assert all(row.abstained for row in diagnostics)


def test_ambiguous_activation_cannot_prove_leader() -> None:
    scene = _scene(_event("A", 1, "a"))
    records, diagnostics = event_authority(
        scene, _beat(_row("a", "A", policy="SAFE_ABSTENTION")),
    )
    assert records == []
    assert [row.conflict_type for row in diagnostics] == ["UNPROVEN_EVENT_CARRIER"]
    assert diagnostics[0].abstained


def test_typed_comparison_outranks_causal_sounding_text_with_diagnostic() -> None:
    scene = _scene(
        _event("A", 1, "a", participant_asset_ids=("b",)),
        assets=[_asset("a", "A", role="primary", semantic_name="block attack"),
                _asset("b", "A", role="supporting")],
        relations=[CanonicalRelation(subject_asset_id="a", object_asset_id="b",
                                     relation_type="PARALLEL_CAUSES")],
    )
    beat = _beat(_row("a", "A"), _row("b", "A"))
    authorities, _ = event_authority(scene, beat)
    decision = SemanticActionResolver().resolve(
        scene, beat.model_copy(update={"event_authorities": authorities}),
    )
    assert decision.action == "COMPARE"
    assert decision.authority == "FINAL_PACKAGE_RELATION"
    assert decision.diagnostics[0].conflict_type == "RELATION_TEXT_ACTION_CONFLICT"
    assert decision.diagnostics[0].source_values["text_action"] == "BLOCK"


def test_free_text_action_fallback_remains_available() -> None:
    scene = _scene(assets=[_asset("a", "A", role="primary", semantic_name="block access")])
    decision = SemanticActionResolver().resolve(scene, _beat())
    assert decision.action == "BLOCK"


def test_conflicting_priority_role_does_not_promote_unsupported_text_action() -> None:
    scene = _scene(assets=[_asset("a", "A", role="supporting", semantic_role="PRIMARY",
                                  semantic_name="block access")])
    decision = SemanticActionResolver().resolve(scene, _beat())
    assert decision.action != "BLOCK"
