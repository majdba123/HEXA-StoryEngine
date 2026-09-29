from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest
from PIL import Image

from app.canonical import CanonicalPackage
from app.final_package import FinalPackageLoader
from app.shared.errors import InvalidPackageError
from tests.test1.factory import DiskPackageShape, write_valid_package


def test_final_package_boundary_returns_canonical_package(tmp_path: Path) -> None:
    source = write_valid_package(tmp_path / "pkg", DiskPackageShape(scenes=1, assets_per_scene=1, locators="all"))
    package = FinalPackageLoader().load(source, tmp_path / "work")
    assert isinstance(package, CanonicalPackage)
    assert package.contract_name == "HEXA_UNIFIED_FINAL_PACKAGE"
    assert package.contract_version == "2.0"
    assert package.has_authoritative_semantics
    assert len(package.scenes) == 1


def test_legacy_package_without_package_json_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "legacy"
    root.mkdir()
    Image.new("RGB", (64, 64), "white").save(root / "scene.png")
    (root / "manifest.json").write_text(json.dumps({"package_version": "1.2"}), encoding="utf-8")
    with pytest.raises(InvalidPackageError, match="legacy 1.x packages are unsupported"):
        FinalPackageLoader().load(root, tmp_path / "work")


def test_zip_traversal_is_rejected_at_boundary(tmp_path: Path) -> None:
    archive = tmp_path / "evil.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("../escape.txt", "bad")
    with pytest.raises(InvalidPackageError):
        FinalPackageLoader().load(archive, tmp_path / "work")
