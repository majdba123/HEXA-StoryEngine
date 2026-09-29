from __future__ import annotations

import json

from app.final_package import FinalPackageLoader
from tests.test1.factory import DiskPackageShape, write_valid_package


def test_generated_semantic_truth_is_preserved_through_canonicalization(tmp_path) -> None:
    source = write_valid_package(
        tmp_path / "source",
        DiskPackageShape(
            scenes=3, assets_per_scene=6, relations=True, dependencies=True,
            dependency_mode="branching", locators="partial", extra_metadata=True,
            compound=True, progression=True, group_count=2,
            group_policy="SIMULTANEOUS_VISUAL_UNIT",
            binding_types=("EXPLICIT", "SUPPORT", "PARENT", "AMBIGUOUS", "SEMANTIC"),
            continuity="transform", reuse_first_asset=True, script_style="arabic",
            namespace="CORRECT",
        ),
    )
    payload = json.loads((source / "package.json").read_text(encoding="utf-8"))
    canonical = FinalPackageLoader().load(source, tmp_path / "work")

    source_scenes = {row["scene_id"]: row for row in payload["scenes"]}
    assert canonical.contract_name == "HEXA_UNIFIED_FINAL_PACKAGE"
    assert canonical.contract_version == "2.0"
    assert canonical.has_authoritative_semantics is True
    assert canonical.script == payload["canonical_script"]
    assert [scene.order for scene in canonical.scenes] == sorted(scene.order for scene in canonical.scenes)

    for scene in canonical.scenes:
        src = source_scenes[scene.id]
        src_assets = {row["asset_id"]: row for row in src["objects"]}
        src_events = {row["semantic_event_id"]: row for row in src["semantic_events"]}

        assert {asset.asset_id for asset in scene.assets} == set(src_assets)
        assert {event.semantic_event_id for event in scene.semantic_events} == set(src_events)
        assert len(scene.semantic_groups) == len(src["semantic_groups"])
        assert len(scene.relations) == len(src["relations"])
        assert scene.progression is not None
        assert scene.progression.event_order == tuple(src["semantic_progression"]["event_order"])

        for asset in scene.assets:
            row = src_assets[asset.asset_id]
            assert str(asset.binding_type) == row["binding_type"]
            assert str(asset.visual_focus) == row["visual_focus"]
            assert asset.semantic_role == row["semantic_role"]
            assert asset.sequence_order == row["sequence_order"]
            assert asset.semantic_event_id == row["semantic_event_id"]
            assert asset.script_span is not None
            assert asset.script_span.global_char_start == row["script_span"]["global_char_start"]
            assert asset.script_span.global_char_end == row["script_span"]["global_char_end"]
            expected_locator = row["visual_locator"]["cx"] is not None
            assert (asset.visual_locator is not None) == expected_locator
            assert str(asset.compound_visual_classification) == row["compound_visual_classification"]
            assert asset.internal_progression_unavailable == row["internal_progression_unavailable"]
            expected_mode = row["continuity"]["mode"]
            assert (asset.continuity is not None) == (expected_mode is not None)
            if asset.continuity is not None:
                assert str(asset.continuity.mode) == expected_mode
                assert asset.continuity.target_asset_id == row["continuity"]["target_asset_id"]

        for event in scene.semantic_events:
            row = src_events[event.semantic_event_id]
            assert event.sequence_order == row["sequence_order"]
            assert event.depends_on_event_ids == tuple(row["depends_on_event_ids"])
            assert event.visual_leader_asset_id == row["visual_leader_asset_id"]
            assert event.participant_asset_ids == tuple(row["participant_asset_ids"])
            assert event.result_asset_ids == tuple(row["result_asset_ids"])

        for relation, row in zip(scene.relations, src["relations"], strict=True):
            assert relation.subject_asset_id == row["subject_asset_id"]
            assert relation.object_asset_id == row["object_asset_id"]
            assert relation.relation_type == row["relation_type"]
