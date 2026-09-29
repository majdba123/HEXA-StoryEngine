from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.final_package import FinalPackageLoader
from app.shared.errors import InvalidPackageError
from tests.test1.factory import DiskPackageShape, write_valid_package


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def _source(tmp_path: Path, *, assets: int = 3) -> Path:
    return write_valid_package(tmp_path / "source", DiskPackageShape(scenes=1, assets_per_scene=assets, locators="all"))


def _package_json(source: Path) -> Path:
    return source / "package.json"


def test_invalid_json_is_classified_as_package_error(tmp_path: Path) -> None:
    source = _source(tmp_path)
    _package_json(source).write_text("{broken", encoding="utf-8")
    with pytest.raises(InvalidPackageError, match="invalid json"):
        FinalPackageLoader().load(source, tmp_path / "work")


@pytest.mark.parametrize(("field", "value"), [("contract", "OTHER_PACKAGE"), ("contract_version", "9.9")])
def test_unsupported_declared_contract_is_rejected(tmp_path: Path, field: str, value: str) -> None:
    source = _source(tmp_path)
    path = _package_json(source)
    payload = _read(path)
    payload[field] = value
    _write(path, payload)
    with pytest.raises(InvalidPackageError, match="invalid Unified Final Package 2.0"):
        FinalPackageLoader().load(source, tmp_path / "work")


def test_unknown_schema_field_is_rejected(tmp_path: Path) -> None:
    source = _source(tmp_path)
    path = _package_json(source)
    payload = _read(path)
    payload["legacy_manifest"] = {}
    _write(path, payload)
    with pytest.raises(InvalidPackageError, match="Extra inputs are not permitted"):
        FinalPackageLoader().load(source, tmp_path / "work")


def test_missing_scene_image_is_rejected(tmp_path: Path) -> None:
    source = _source(tmp_path)
    next((source / "images").glob("*.png")).unlink()
    with pytest.raises(InvalidPackageError, match="missing scene image"):
        FinalPackageLoader().load(source, tmp_path / "work")


def test_duplicate_object_id_is_rejected(tmp_path: Path) -> None:
    source = _source(tmp_path)
    path = _package_json(source)
    payload = _read(path)
    payload["scenes"][0]["objects"].append(dict(payload["scenes"][0]["objects"][0]))
    _write(path, payload)
    with pytest.raises(InvalidPackageError, match="duplicate object asset_id"):
        FinalPackageLoader().load(source, tmp_path / "work")


def test_missing_event_dependency_is_rejected(tmp_path: Path) -> None:
    source = _source(tmp_path)
    path = _package_json(source)
    payload = _read(path)
    payload["scenes"][0]["semantic_events"][1]["depends_on_event_ids"] = ["MISSING_EVENT"]
    _write(path, payload)
    with pytest.raises(InvalidPackageError, match="reference is missing: event dependency"):
        FinalPackageLoader().load(source, tmp_path / "work")


def test_event_dependency_cycle_is_rejected(tmp_path: Path) -> None:
    source = _source(tmp_path)
    path = _package_json(source)
    payload = _read(path)
    first, second = payload["scenes"][0]["semantic_events"][:2]
    first["depends_on_event_ids"] = [second["semantic_event_id"]]
    second["depends_on_event_ids"] = [first["semantic_event_id"]]
    _write(path, payload)
    with pytest.raises(InvalidPackageError, match="dependency cycle"):
        FinalPackageLoader().load(source, tmp_path / "work")


def test_invalid_visual_locator_is_rejected(tmp_path: Path) -> None:
    source = _source(tmp_path)
    path = _package_json(source)
    payload = _read(path)
    payload["scenes"][0]["objects"][0]["visual_locator"]["cx"] = 1.5
    _write(path, payload)
    with pytest.raises(InvalidPackageError, match="visual_locator"):
        FinalPackageLoader().load(source, tmp_path / "work")


def test_missing_parent_reference_is_rejected(tmp_path: Path) -> None:
    source = _source(tmp_path)
    path = _package_json(source)
    payload = _read(path)
    payload["scenes"][0]["objects"][0]["parent_asset_id"] = "MISSING_PARENT"
    _write(path, payload)
    with pytest.raises(InvalidPackageError, match="object parent is missing"):
        FinalPackageLoader().load(source, tmp_path / "work")


def test_scene_image_path_traversal_is_rejected(tmp_path: Path) -> None:
    source = _source(tmp_path)
    path = _package_json(source)
    payload = _read(path)
    payload["scenes"][0]["image"] = "../outside.png"
    _write(path, payload)
    with pytest.raises(InvalidPackageError, match="path escapes Final Package"):
        FinalPackageLoader().load(source, tmp_path / "work")


def test_partially_populated_locator_is_rejected(tmp_path: Path) -> None:
    source = _source(tmp_path)
    path = _package_json(source)
    payload = _read(path)
    payload["scenes"][0]["objects"][0]["visual_locator"]["width"] = None
    _write(path, payload)
    with pytest.raises(InvalidPackageError, match="visual_locator is incomplete"):
        FinalPackageLoader().load(source, tmp_path / "work")


def test_legacy_companion_file_is_forbidden_even_with_valid_package_json(tmp_path: Path) -> None:
    source = _source(tmp_path)
    (source / "manifest.json").write_text("{}", encoding="utf-8")
    with pytest.raises(InvalidPackageError, match="legacy companion files are forbidden"):
        FinalPackageLoader().load(source, tmp_path / "work")


def test_group_membership_mismatch_is_rejected(tmp_path: Path) -> None:
    source = _source(tmp_path)
    path = _package_json(source)
    payload = _read(path)
    payload["scenes"][0]["semantic_groups"][0]["asset_ids"] = []
    _write(path, payload)
    with pytest.raises(InvalidPackageError, match="semantic group membership mismatch"):
        FinalPackageLoader().load(source, tmp_path / "work")


def test_event_membership_mismatch_is_rejected(tmp_path: Path) -> None:
    source = _source(tmp_path)
    path = _package_json(source)
    payload = _read(path)
    payload["scenes"][0]["semantic_events"][0]["visual_leader_asset_id"] = payload["scenes"][0]["objects"][1]["asset_id"]
    _write(path, payload)
    with pytest.raises(InvalidPackageError, match="semantic event ownership mismatch"):
        FinalPackageLoader().load(source, tmp_path / "work")


def test_scene_image_must_live_under_declared_image_directory(tmp_path: Path) -> None:
    source = _source(tmp_path)
    path = _package_json(source)
    payload = _read(path)
    image_rel = payload["scenes"][0]["image"]
    image_path = source / image_rel
    target = source / "outside.png"
    target.write_bytes(image_path.read_bytes())
    payload["scenes"][0]["image"] = "outside.png"
    _write(path, payload)
    with pytest.raises(InvalidPackageError, match="image_spec.directory"):
        FinalPackageLoader().load(source, tmp_path / "work")


def test_scene_image_extension_must_match_image_spec(tmp_path: Path) -> None:
    source = _source(tmp_path)
    path = _package_json(source)
    payload = _read(path)
    payload["image_spec"]["format"] = "jpg"
    _write(path, payload)
    with pytest.raises(InvalidPackageError, match="extension does not match image_spec"):
        FinalPackageLoader().load(source, tmp_path / "work")


def test_nullable_fields_are_still_required_for_schema_uniformity(tmp_path: Path) -> None:
    source = _source(tmp_path)
    path = _package_json(source)
    payload = _read(path)
    del payload["scenes"][0]["objects"][0]["continuity"]
    _write(path, payload)
    with pytest.raises(InvalidPackageError, match="Field required"):
        FinalPackageLoader().load(source, tmp_path / "work")
