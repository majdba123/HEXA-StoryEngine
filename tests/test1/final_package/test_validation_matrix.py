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
    path.write_text(json.dumps(value), encoding="utf-8")


def _source(tmp_path: Path, *, assets: int = 3) -> Path:
    return write_valid_package(
        tmp_path / "source",
        DiskPackageShape(scenes=1, assets_per_scene=assets, locators="all"),
    )


def test_invalid_json_is_classified_as_package_error(tmp_path: Path) -> None:
    source = _source(tmp_path)
    (source / "semantic_bindings.json").write_text("{broken", encoding="utf-8")
    with pytest.raises(InvalidPackageError, match="invalid json"):
        FinalPackageLoader().load(source, tmp_path / "work")


@pytest.mark.parametrize(
    ("file_name", "field", "value", "message"),
    [
        ("manifest.json", "package_version", "9.9", "unsupported Final Package version"),
        ("manifest.json", "package_schema", "OTHER_PACKAGE", "unsupported Final Package schema"),
        ("semantic_bindings.json", "schema_version", "9.9", "unsupported semantic bindings version"),
        ("semantic_bindings.json", "schema_name", "OTHER_BINDINGS", "unsupported semantic bindings schema"),
    ],
)
def test_unsupported_declared_contract_is_rejected(
    tmp_path: Path, file_name: str, field: str, value: str, message: str
) -> None:
    source = _source(tmp_path)
    path = source / file_name
    payload = _read(path)
    payload[field] = value
    _write(path, payload)
    with pytest.raises(InvalidPackageError, match=message):
        FinalPackageLoader().load(source, tmp_path / "work")


def test_missing_scene_image_is_rejected(tmp_path: Path) -> None:
    source = _source(tmp_path)
    next((source / "scenes").glob("*.png")).unlink()
    with pytest.raises(InvalidPackageError):
        FinalPackageLoader().load(source, tmp_path / "work")


def test_duplicate_semantic_asset_id_is_rejected(tmp_path: Path) -> None:
    source = _source(tmp_path)
    path = source / "semantic_bindings.json"
    payload = _read(path)
    payload["scenes"][0]["assets"].append(dict(payload["scenes"][0]["assets"][0]))
    _write(path, payload)
    with pytest.raises(InvalidPackageError, match="duplicate semantic binding asset"):
        FinalPackageLoader().load(source, tmp_path / "work")


def test_missing_event_dependency_is_rejected(tmp_path: Path) -> None:
    source = _source(tmp_path)
    path = source / "semantic_bindings.json"
    payload = _read(path)
    payload["scenes"][0]["semantic_events"][1]["depends_on_event_ids"] = ["MISSING_EVENT"]
    _write(path, payload)
    with pytest.raises(InvalidPackageError, match="dependency is missing"):
        FinalPackageLoader().load(source, tmp_path / "work")


def test_event_dependency_cycle_is_rejected(tmp_path: Path) -> None:
    source = _source(tmp_path)
    path = source / "semantic_bindings.json"
    payload = _read(path)
    first, second = payload["scenes"][0]["semantic_events"][:2]
    first["depends_on_event_ids"] = [second["semantic_event_id"]]
    second["depends_on_event_ids"] = [first["semantic_event_id"]]
    _write(path, payload)
    with pytest.raises(InvalidPackageError, match="dependency cycle"):
        FinalPackageLoader().load(source, tmp_path / "work")


def test_invalid_visual_locator_is_rejected(tmp_path: Path) -> None:
    source = _source(tmp_path)
    path = source / "semantic_bindings.json"
    payload = _read(path)
    payload["scenes"][0]["assets"][0]["visual_locator"]["cx"] = 1.5
    _write(path, payload)
    with pytest.raises(InvalidPackageError, match="visual_locator"):
        FinalPackageLoader().load(source, tmp_path / "work")


def test_missing_parent_reference_is_rejected(tmp_path: Path) -> None:
    source = _source(tmp_path)
    path = source / "semantic_bindings.json"
    payload = _read(path)
    payload["scenes"][0]["assets"][0]["parent_asset_id"] = "MISSING_PARENT"
    _write(path, payload)
    with pytest.raises(InvalidPackageError, match="parent is missing"):
        FinalPackageLoader().load(source, tmp_path / "work")
