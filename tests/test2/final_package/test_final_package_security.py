from __future__ import annotations

import json
from pathlib import Path
from zipfile import ZipFile

import pytest

from app.final_package import FinalPackageLoader
from app.shared.errors import InvalidPackageError
from tests.support.unified_package import write_unified_package


def _package(tmp_path: Path, *, script: str = "alpha beta") -> Path:
    return write_unified_package(
        tmp_path / "package",
        script=script,
        package_id="security-v2",
        scenes=[{
            "scene_id": "SCENE_001",
            "order": 0,
            "script_span": {"text": script, "global_char_start": 0, "global_char_end": len(script)},
            "assets": [
                {
                    "asset_id": "a", "script_text": "alpha",
                    "script_span": {"text": "alpha", "global_char_start": 0, "global_char_end": 5},
                    "appear_trigger": {"text": "alpha", "global_char_start": 0, "global_char_end": 5},
                    "binding_type": "EXPLICIT", "semantic_group_id": "g", "sequence_order": 1,
                    "semantic_event_id": "E1", "visual_focus": "PRIMARY",
                    "visual_locator": {"coordinate_space": "normalized_scene", "cx": 0.3, "cy": 0.5, "width": 0.2, "height": 0.2},
                },
                {
                    "asset_id": "b", "script_text": "beta",
                    "script_span": {"text": "beta", "global_char_start": 6, "global_char_end": 10},
                    "appear_trigger": {"text": "beta", "global_char_start": 6, "global_char_end": 10},
                    "binding_type": "SEMANTIC", "semantic_group_id": "g", "sequence_order": 2,
                    "semantic_event_id": "E2", "visual_focus": "RESULT",
                    "visual_locator": {"coordinate_space": "normalized_scene", "cx": 0.7, "cy": 0.5, "width": 0.2, "height": 0.2},
                },
            ],
            "semantic_groups": [{"semantic_group_id": "g", "script_text": script, "asset_ids": ["a", "b"]}],
            "semantic_events": [
                {"semantic_event_id": "E1", "script_text": "alpha", "script_span": {"text": "alpha", "global_char_start": 0, "global_char_end": 5}, "visual_leader_asset_id": "a", "text_anchor_asset_id": "a", "sequence_order": 1},
                {"semantic_event_id": "E2", "script_text": "beta", "script_span": {"text": "beta", "global_char_start": 6, "global_char_end": 10}, "visual_leader_asset_id": "b", "result_asset_ids": ["b"], "text_anchor_asset_id": "b", "sequence_order": 2, "depends_on_event_ids": ["E1"]},
            ],
            "relations": [{"relation_id": "R1", "subject_asset_id": "a", "relation_type": "ENABLES", "object_asset_id": "b"}],
            "semantic_progression": {"type": "GENERIC_PROGRESS", "event_order": ["E1", "E2"]},
        }],
    )


def _load_json(package: Path) -> dict:
    return json.loads((package / "package.json").read_text(encoding="utf-8"))


def _save_json(package: Path, payload: dict) -> None:
    (package / "package.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_rejects_zip_path_traversal(tmp_path: Path) -> None:
    archive = tmp_path / "bad.zip"
    with ZipFile(archive, "w") as handle:
        handle.writestr("../escape.png", b"bad")
    with pytest.raises(InvalidPackageError, match="unsafe path"):
        FinalPackageLoader().load(archive, tmp_path / "work")


def test_rejects_scene_image_outside_package(tmp_path: Path) -> None:
    package = _package(tmp_path)
    payload = _load_json(package)
    payload["scenes"][0]["image"] = "../outside.png"
    _save_json(package, payload)
    with pytest.raises(InvalidPackageError, match="path escapes Final Package"):
        FinalPackageLoader().load(package, tmp_path / "work")


def test_canonical_script_is_inline_authority(tmp_path: Path) -> None:
    package = _package(tmp_path, script="alpha beta")
    loaded = FinalPackageLoader().load(package, tmp_path / "work")
    assert loaded.script == "alpha beta"
    assert loaded.has_authoritative_semantics is True
    assert loaded.contract_name == "HEXA_UNIFIED_FINAL_PACKAGE"
    assert loaded.contract_version == "2.0"


def test_legacy_1x_package_is_rejected(tmp_path: Path) -> None:
    package = tmp_path / "legacy"
    package.mkdir()
    (package / "manifest.json").write_text('{"package_version":"1.2"}', encoding="utf-8")
    with pytest.raises(InvalidPackageError, match="legacy 1.x packages are unsupported"):
        FinalPackageLoader().load(package, tmp_path / "work")


def test_parent_reference_must_exist(tmp_path: Path) -> None:
    package = _package(tmp_path)
    payload = _load_json(package)
    payload["scenes"][0]["objects"][0]["parent_asset_id"] = "missing"
    _save_json(package, payload)
    with pytest.raises(InvalidPackageError, match="object parent is missing"):
        FinalPackageLoader().load(package, tmp_path / "work")


def test_group_membership_must_reference_existing_objects(tmp_path: Path) -> None:
    package = _package(tmp_path)
    payload = _load_json(package)
    payload["scenes"][0]["semantic_groups"][0]["asset_ids"].append("missing")
    _save_json(package, payload)
    with pytest.raises(InvalidPackageError, match="reference is missing: semantic group"):
        FinalPackageLoader().load(package, tmp_path / "work")


def test_precise_span_must_match_canonical_script(tmp_path: Path) -> None:
    package = _package(tmp_path)
    payload = _load_json(package)
    payload["scenes"][0]["objects"][0]["script_span"]["text"] = "invented"
    _save_json(package, payload)
    with pytest.raises(InvalidPackageError, match="script span text mismatch"):
        FinalPackageLoader().load(package, tmp_path / "work")


def test_visual_locator_must_fit_normalized_scene(tmp_path: Path) -> None:
    package = _package(tmp_path)
    payload = _load_json(package)
    payload["scenes"][0]["objects"][0]["visual_locator"].update({"cx": 0.95, "width": 0.2})
    _save_json(package, payload)
    with pytest.raises(InvalidPackageError, match="exceeds horizontal scene bounds"):
        FinalPackageLoader().load(package, tmp_path / "work")


def test_partial_visual_locator_is_rejected(tmp_path: Path) -> None:
    package = _package(tmp_path)
    payload = _load_json(package)
    payload["scenes"][0]["objects"][0]["visual_locator"]["width"] = None
    _save_json(package, payload)
    with pytest.raises(InvalidPackageError, match="visual_locator is incomplete"):
        FinalPackageLoader().load(package, tmp_path / "work")


def test_event_dependency_cycle_is_rejected(tmp_path: Path) -> None:
    package = _package(tmp_path)
    payload = _load_json(package)
    events = payload["scenes"][0]["semantic_events"]
    events[0]["depends_on_event_ids"] = ["E2"]
    _save_json(package, payload)
    with pytest.raises(InvalidPackageError, match="dependency cycle"):
        FinalPackageLoader().load(package, tmp_path / "work")


def test_relation_refs_must_exist(tmp_path: Path) -> None:
    package = _package(tmp_path)
    payload = _load_json(package)
    payload["scenes"][0]["relations"][0]["object_asset_id"] = "missing"
    _save_json(package, payload)
    with pytest.raises(InvalidPackageError, match="reference is missing: relation"):
        FinalPackageLoader().load(package, tmp_path / "work")
