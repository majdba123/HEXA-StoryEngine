from pathlib import Path
from zipfile import ZipFile

import pytest

from app.input.loader import FinalPackageLoader
from app.shared.errors import InvalidPackageError


def test_rejects_zip_path_traversal(tmp_path: Path) -> None:
    archive = tmp_path / "bad.zip"
    with ZipFile(archive, "w") as handle:
        handle.writestr("../escape.png", b"bad")

    with pytest.raises(InvalidPackageError, match="unsafe path"):
        FinalPackageLoader().load(archive, tmp_path / "work")


def test_rejects_manifest_scene_outside_package(tmp_path: Path) -> None:
    package = tmp_path / "package"
    package.mkdir()
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"x")
    (package / "manifest.json").write_text(
        '{"scenes":[{"id":"bad","image":"../outside.png"}]}',
        encoding="utf-8",
    )

    with pytest.raises(InvalidPackageError, match="escapes Final Package"):
        FinalPackageLoader().load(package, tmp_path / "work")


def test_loads_canonical_script_declared_by_final_package(tmp_path: Path) -> None:
    package = tmp_path / "package"
    scenes = package / "scenes"
    scenes.mkdir(parents=True)
    (scenes / "SCENE_001.png").write_bytes(b"png")
    (package / "canonical_script.txt").write_text("نص الاختبار", encoding="utf-8")
    (package / "manifest.json").write_text(
        '{"canonical_script":"canonical_script.txt"}',
        encoding="utf-8",
    )

    loaded = FinalPackageLoader().load(package, tmp_path / "work")

    assert loaded.script == "نص الاختبار"
