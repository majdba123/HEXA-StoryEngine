from __future__ import annotations

import json
from pathlib import Path

from app.final_package import FinalPackageLoader
from tests.support.unified_package import write_unified_package


def _package(tmp_path: Path) -> Path:
    script = "alpha beta"
    scene = {
        "scene_id": "SCENE_001",
        "order": 0,
        "script_span": {"text": script, "global_char_start": 0, "global_char_end": len(script)},
        "assets": [
            {
                "asset_id": "A1",
                "script_text": "alpha",
                "script_span": {"global_char_start": 0, "global_char_end": 5},
                "appear_trigger": {"global_char_start": 0, "global_char_end": 5},
                "binding_type": "EXPLICIT",
                "semantic_group_id": "G1",
                "semantic_event_id": "E1",
                "sequence_order": 1,
                "anchor_granularity": "EXACT_WORD",
                "visual_focus": "PRIMARY",
                "compound_visual_classification": "SEPARABLE_SAFE",
                "visual_locator": {
                    "coordinate_space": "normalized_scene",
                    "cx": 0.3,
                    "cy": 0.5,
                    "width": 0.2,
                    "height": 0.3,
                },
            },
            {
                "asset_id": "A2",
                "script_text": "beta",
                "script_span": {"global_char_start": 6, "global_char_end": 10},
                "appear_trigger": {"global_char_start": 6, "global_char_end": 10},
                "binding_type": "EXPLICIT",
                "semantic_group_id": "G1",
                "semantic_event_id": "E2",
                "sequence_order": 2,
                "anchor_granularity": "EXACT_WORD",
                "visual_focus": "RESULT",
                "semantic_role": "RESULT",
                "compound_visual_classification": "SEPARABLE_SAFE",
                "visual_locator": {
                    "coordinate_space": "normalized_scene",
                    "cx": 0.7,
                    "cy": 0.5,
                    "width": 0.2,
                    "height": 0.3,
                },
            },
        ],
        "semantic_groups": [
            {
                "semantic_group_id": "G1",
                "script_text": script,
                "animation_policy": "SEQUENTIAL_WITHIN_PHRASE",
                "asset_ids": ["A1", "A2"],
            }
        ],
        "semantic_events": [
            {
                "semantic_event_id": "E1",
                "script_text": "alpha",
                "script_span": {"global_char_start": 0, "global_char_end": 5},
                "anchor_granularity": "EXACT_WORD",
                "sequence_order": 1,
                "visual_leader_asset_id": "A1",
                "participant_asset_ids": [],
                "context_asset_ids": [],
                "result_asset_ids": [],
                "text_anchor_asset_id": "A1",
                "depends_on_event_ids": [],
            },
            {
                "semantic_event_id": "E2",
                "script_text": "beta",
                "script_span": {"global_char_start": 6, "global_char_end": 10},
                "anchor_granularity": "EXACT_WORD",
                "sequence_order": 2,
                "visual_leader_asset_id": "A2",
                "participant_asset_ids": [],
                "context_asset_ids": [],
                "result_asset_ids": ["A2"],
                "text_anchor_asset_id": "A2",
                "depends_on_event_ids": ["E1"],
            },
        ],
        "relations": [
            {
                "relation_id": "R1",
                "subject_asset_id": "A1",
                "relation_type": "ENABLES",
                "object_asset_id": "A2",
                "script_text": script,
                "script_span": {"global_char_start": 0, "global_char_end": len(script)},
            }
        ],
        "semantic_progression": {"type": "LINEAR", "event_order": ["E1", "E2"]},
    }
    return write_unified_package(
        tmp_path / "package",
        script=script,
        scenes=[scene],
        package_id="unified-contract-checkpoint",
        image_size=(320, 180),
    )


def test_unified_package_is_the_only_runtime_semantic_authority(tmp_path: Path) -> None:
    path = _package(tmp_path)
    payload = json.loads((path / "package.json").read_text(encoding="utf-8"))
    assert payload["contract"] == "HEXA_UNIFIED_FINAL_PACKAGE"
    assert payload["contract_version"] == "2.0"
    assert not (path / "manifest.json").exists()
    assert not (path / "scene_plan.json").exists()
    assert not (path / "semantic_bindings.json").exists()

    package = FinalPackageLoader().load(path, tmp_path / "work")
    assert package.contract_name == "HEXA_UNIFIED_FINAL_PACKAGE"
    assert package.contract_version == "2.0"
    assert package.has_authoritative_semantics is True
    assert package.script == "alpha beta"
    assert [event.semantic_event_id for event in package.scenes[0].semantic_events] == ["E1", "E2"]
    assert package.scenes[0].relations[0].relation_type == "ENABLES"


def test_unified_package_runtime_contract_is_canonical_not_file_shaped(tmp_path: Path) -> None:
    package = FinalPackageLoader().load(_package(tmp_path), tmp_path / "work")
    assert not hasattr(package, "manifest")
    assert not hasattr(package, "scene_plan")
    assert not hasattr(package, "semantic_bindings")
    assert not hasattr(package, "manifest_objects")
    assert not hasattr(package, "manifest_assets")
    assert package.scene_by_id["SCENE_001"].assets[0].asset_id == "A1"
    assert package.event_by_id["E2"].depends_on_event_ids == ("E1",)
