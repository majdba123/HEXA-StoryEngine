from __future__ import annotations

from app.canonical import CanonicalNormalizer
from app.final_package import FinalPackageLoader
from tests.test1.factory import DiskPackageShape, write_valid_package


def test_generated_semantic_truth_is_preserved_through_canonicalization(tmp_path) -> None:
    source = write_valid_package(
        tmp_path / "source",
        DiskPackageShape(
            scenes=3,
            assets_per_scene=6,
            relations=True,
            dependencies=True,
            dependency_mode="branching",
            locators="partial",
            extra_metadata=True,
            compound=True,
            progression=True,
            group_count=2,
            group_policy="SIMULTANEOUS_VISUAL_UNIT",
            binding_types=("EXPLICIT", "SUPPORT", "PARENT", "AMBIGUOUS", "SEMANTIC"),
            continuity="transform",
            reuse_first_asset=True,
            script_style="arabic",
            namespace="CORRECT",
        ),
    )
    raw = FinalPackageLoader().load(source, tmp_path / "work")
    canonical = CanonicalNormalizer().normalize(raw)

    raw_scenes = {row["scene_id"]: row for row in raw.semantic_bindings["scenes"]}
    assert [scene.order for scene in canonical.scenes] == sorted(scene.order for scene in canonical.scenes)

    for scene in canonical.scenes:
        raw_scene = raw_scenes[scene.id]
        raw_assets = {row["asset_id"]: row for row in raw_scene["assets"]}
        raw_events = {row["semantic_event_id"]: row for row in raw_scene["semantic_events"]}

        assert {asset.asset_id for asset in scene.assets} == set(raw_assets)
        assert {event.semantic_event_id for event in scene.semantic_events} == set(raw_events)
        assert len(scene.semantic_groups) == len(raw_scene["semantic_groups"])
        assert len(scene.relations) == len(raw_scene["relations"])
        assert scene.progression is not None
        assert scene.progression.event_order == tuple(raw_scene["progression"]["event_order"])

        for asset in scene.assets:
            source_asset = raw_assets[asset.asset_id]
            assert str(asset.binding_type) == source_asset["binding_type"]
            assert str(asset.visual_focus) == source_asset["visual_focus"]
            assert asset.semantic_role == source_asset["semantic_role"]
            assert asset.sequence_order == source_asset["sequence_order"]
            assert asset.semantic_event_id == source_asset["semantic_event_id"]
            assert asset.script_span is not None
            assert asset.script_span.global_char_start == source_asset["script_span"]["global_char_start"]
            assert asset.script_span.global_char_end == source_asset["script_span"]["global_char_end"]
            assert (asset.visual_locator is not None) == ("visual_locator" in source_asset)
            assert str(asset.compound_visual_classification) == source_asset["compound_visual_classification"]
            assert asset.internal_progression_unavailable == source_asset["internal_progression_unavailable"]
            if "continuity" in source_asset:
                assert asset.continuity is not None
                assert str(asset.continuity.mode) == source_asset["continuity"]["mode"]
                assert asset.continuity.target_asset_id == source_asset["continuity"].get("target_asset_id")

        for event in scene.semantic_events:
            source_event = raw_events[event.semantic_event_id]
            assert event.sequence_order == source_event["sequence_order"]
            assert event.depends_on_event_ids == tuple(source_event["depends_on_event_ids"])
            assert event.visual_leader_asset_id == source_event["visual_leader_asset_id"]
            assert event.participant_asset_ids == tuple(source_event["participant_asset_ids"])
            assert event.result_asset_ids == tuple(source_event["result_asset_ids"])

        for relation, source_relation in zip(scene.relations, raw_scene["relations"]):
            assert relation.subject_asset_id == source_relation["subject_asset_id"]
            assert relation.object_asset_id == source_relation["object_asset_id"]
            assert relation.relation_type == source_relation["relation_type"]
