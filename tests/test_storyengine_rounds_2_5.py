from pathlib import Path

from app.choreography import ChoreographyDirector
from app.composition import CompositionPlanner
from app.diagnostics import StorytellingValidator
from app.models import (
    PackageModel,
    SceneSource,
    StoryBeat,
    StoryEntity,
    StoryRelation,
    StorySemanticContext,
    TextPlan,
    VisualAsset,
)
from app.motion import MotionPlanner


def asset(asset_id: str, scene_id: str, role: str, x: int) -> VisualAsset:
    return VisualAsset(
        id=asset_id,
        scene_id=scene_id,
        role=role,
        image_path=Path(f"/{asset_id}.png"),
        extraction_method="test",
        source_bbox=(x, 120, 250, 300),
        source_canvas_width=1000,
        source_canvas_height=700,
        source_area_ratio=0.11,
    )


def semantic_case(
    relationship: str = "TRANSFERS_TO",
    intent: str = "TRANSFER",
) -> tuple[PackageModel, StoryBeat, list[VisualAsset]]:
    scene_id = "scene-generic"
    scene = SceneSource(
        id=scene_id,
        image_path=Path("/scene.png"),
        order=0,
        purpose="EXPLAIN_GENERIC_FLOW",
        visual_concept="generic subject changes generic object",
        relation_to_previous="CONTINUES_STORY",
        units=[
            {
                "unit_id": "SUBJECT",
                "semantic_name": "generic_subject",
                "type": "GROUP",
                "role": "PRIMARY",
                "semantic_intent": intent,
                "interaction_target": "OBJECT",
                "relationship": relationship,
            },
            {
                "unit_id": "OBJECT",
                "semantic_name": "generic_object",
                "type": "GROUP",
                "role": "SUPPORTING",
            },
        ],
        visual_progression=[
            {
                "event_id": "EVENT_1",
                "order": 1,
                "action": intent,
                "targets": ["SUBJECT", "OBJECT"],
            }
        ],
    )
    package = PackageModel(
        root=Path("/tmp"), package_id="generic", script="alpha beta", scenes=[scene]
    )
    beat = StoryBeat(
        id="beat-001",
        scene_id=scene_id,
        start=0.0,
        end=2.0,
        audio_start=0.2,
        audio_end=1.8,
        narration="alpha beta",
        primary_asset_ids=["a"],
        support_asset_ids=["b"],
        action="REVEAL_DETAIL",
        semantic_targets=["SUBJECT", "OBJECT"],
        semantic_context=StorySemanticContext(
            story_role="ACTION",
            entities=[
                StoryEntity(
                    unit_id="SUBJECT",
                    semantic_name="generic_subject",
                    entity_type="GROUP",
                    role="PRIMARY",
                    semantic_intent=intent,
                ),
                StoryEntity(
                    unit_id="OBJECT",
                    semantic_name="generic_object",
                    entity_type="GROUP",
                    role="SUPPORTING",
                ),
            ],
            relations=[
                StoryRelation(
                    source_unit_id="SUBJECT",
                    target_unit_id="OBJECT",
                    kind=relationship,
                    authority="FINAL_PACKAGE_INTERACTION_TARGET",
                    confidence=1.0,
                    causal=True,
                )
            ],
            subject_unit_ids=["SUBJECT"],
            object_unit_ids=["OBJECT"],
            evidence=[f"relationship:{relationship}"],
            confidence=1.0,
            tension=0.7,
        ),
    )
    assets = [asset("a", scene_id, "primary", 100), asset("b", scene_id, "support", 650)]
    return package, beat, assets


def test_round2_final_package_relationship_becomes_executable_interaction() -> None:
    package, beat, assets = semantic_case("BLOCKS", "BLOCK")
    directive = ChoreographyDirector().plan(package, [beat], assets).directives[0]

    assert directive.interaction is not None
    assert directive.interaction.semantic_action == "BLOCK"
    assert directive.interaction.authority == "FINAL_PACKAGE_INTERACTION_TARGET"
    assert directive.interaction.executable is True
    assert directive.has_meaningful_state_change is True


def test_round3_composition_uses_semantic_state_without_dropping_assets() -> None:
    package, beat, assets = semantic_case()
    choreography = ChoreographyDirector().plan(package, [beat], assets)
    authored = CompositionPlanner().plan([beat], assets)
    directed = CompositionPlanner().plan([beat], assets, choreography)

    assert {item.asset_id for item in authored[0].items} == {
        item.asset_id for item in directed[0].items
    }
    assert directed[0].state_name != "AUTHORED"
    assert directed[0].state_evidence


def test_round3_motion_has_no_decorative_shake_jitter_or_wiggle() -> None:
    package, beat, assets = semantic_case()
    choreography = ChoreographyDirector().plan(package, [beat], assets)
    composition = CompositionPlanner().plan([beat], assets, choreography)
    motion = MotionPlanner().plan([beat], composition, choreography)
    names = [cue.params["program"]["name"] for cue in motion]

    assert names
    assert not any(
        token in name.lower()
        for name in names
        for token in ("jitter", "shake", "wiggle")
    )


def test_round5_semantics_generalize_across_unrelated_domains() -> None:
    actions = []
    for domain in ("finance", "commerce", "education"):
        package, beat, assets = semantic_case("BLOCKS", "BLOCK")
        package.scenes[0].units[0]["semantic_name"] = f"{domain}_subject"
        package.scenes[0].units[1]["semantic_name"] = f"{domain}_object"
        actions.append(
            ChoreographyDirector().plan(package, [beat], assets).directives[0].action
        )

    assert actions == ["BLOCK", "BLOCK", "BLOCK"]


def test_round5_storytelling_validator_accepts_semantic_authoring_chain() -> None:
    package, beat, assets = semantic_case()
    choreography = ChoreographyDirector().plan(package, [beat], assets)
    composition = CompositionPlanner().plan([beat], assets, choreography)
    motion = MotionPlanner().plan([beat], composition, choreography)

    report = StorytellingValidator.validate(
        package=package,
        story=[beat],
        choreography=choreography,
        composition=composition,
        motion=motion,
        text=TextPlan(),
        text_motion=[],
    )

    assert report.ready_for_render_review is True
    assert report.represented_relationships == report.explicit_relationships
    assert report.anti_jitter_pass is True
