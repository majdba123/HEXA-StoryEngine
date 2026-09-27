from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest
from PIL import Image

from app.final_package import FinalPackageLoader, RawFinalPackage
from app.shared.errors import InvalidPackageError


def _write_minimal(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (64, 64), "white").save(root / "scene.png")
    (root / "script.txt").write_text("alpha", encoding="utf-8")
    (root / "manifest.json").write_text(json.dumps({
        "package_id": "minimal",
        "script": "script.txt",
        "scenes": [{"id": "s1", "image": "scene.png"}],
    }), encoding="utf-8")
    return root


def test_final_package_boundary_returns_raw_typed_model(tmp_path: Path) -> None:
    raw = FinalPackageLoader().load(_write_minimal(tmp_path / "pkg"), tmp_path / "work")
    assert isinstance(raw, RawFinalPackage)
    assert raw.package_id
    assert len(raw.scenes) == 1


def test_zip_traversal_is_rejected_at_boundary(tmp_path: Path) -> None:
    archive = tmp_path / "evil.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("../escape.txt", "bad")
    with pytest.raises(InvalidPackageError):
        FinalPackageLoader().load(archive, tmp_path / "work")
