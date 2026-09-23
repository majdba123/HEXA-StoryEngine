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


def test_loads_and_validates_optional_semantic_bindings(tmp_path: Path) -> None:
    package = tmp_path / "package"
    scenes = package / "scenes"
    scenes.mkdir(parents=True)
    (scenes / "SCENE_001.png").write_bytes(b"png")
    (package / "canonical_script.txt").write_text("hello world", encoding="utf-8")
    (package / "semantic_bindings.json").write_text(
        '{"schema_name":"HEXA_SEMANTIC_BINDINGS","scenes":[{"scene_id":"SCENE_001",'
        '"assets":[{"scene_id":"SCENE_001","asset_id":"icon","script_text":"hello world",'
        '"parent_asset_id":null}]}]}',
        encoding="utf-8",
    )

    loaded = FinalPackageLoader().load(package, tmp_path / "work")

    assert loaded.semantic_bindings["schema_name"] == "HEXA_SEMANTIC_BINDINGS"
    assert loaded.semantic_bindings["scenes"][0]["assets"][0]["asset_id"] == "icon"


def test_rejects_broken_semantic_binding_parent(tmp_path: Path) -> None:
    package = tmp_path / "package"
    scenes = package / "scenes"
    scenes.mkdir(parents=True)
    (scenes / "SCENE_001.png").write_bytes(b"png")
    (package / "semantic_bindings.json").write_text(
        '{"schema_name":"HEXA_SEMANTIC_BINDINGS","scenes":[{"scene_id":"SCENE_001",'
        '"assets":[{"asset_id":"child","script_text":"hello","parent_asset_id":"missing"}]}]}',
        encoding="utf-8",
    )

    with pytest.raises(InvalidPackageError, match="parent is missing"):
        FinalPackageLoader().load(package, tmp_path / "work")


def test_loads_asset_level_semantic_bindings_contract(tmp_path: Path) -> None:
    package = tmp_path / "package"
    scenes = package / "scenes"
    scenes.mkdir(parents=True)
    (scenes / "SCENE_001.png").write_bytes(b"png")
    (package / "canonical_script.txt").write_text("alpha beta", encoding="utf-8")
    (package / "scene_plan.json").write_text(
        '{"scenes":[{"scene_id":"SCENE_001","order":1,'
        '"image":"scenes/SCENE_001.png","script_span":'
        '{"global_char_start":0,"global_char_end":10,"text":"alpha beta"},'
        '"units":[{"unit_id":"intent-a","type":"VISUAL_ASSET_INTENT"},'
        '{"unit_id":"intent-b","type":"VISUAL_ASSET_INTENT"}]}]}',
        encoding="utf-8",
    )
    (package / "semantic_bindings.json").write_text(
        '{"schema_name":"HEXA_ASSET_LEVEL_SEMANTIC_BINDINGS",'
        '"asset_is_semantic_intent_not_cutout":true,"no_fixed_timing":true,'
        '"scenes":[{"scene_id":"SCENE_001","semantic_groups":['
        '{"semantic_group_id":"g","script_text":"alpha beta",'
        '"animation_policy":"SEQUENTIAL_WITHIN_PHRASE",'
        '"asset_ids":["intent-a","intent-b"]}],"assets":['
        '{"asset_id":"intent-a","script_text":"alpha beta",'
        '"binding_type":"EXPLICIT","semantic_group_id":"g",'
        '"sequence_order":1,"confidence":1.0,"parent_asset_id":null},'
        '{"asset_id":"intent-b","script_text":"alpha beta",'
        '"binding_type":"SEMANTIC","semantic_group_id":"g",'
        '"sequence_order":2,"confidence":0.9,"parent_asset_id":null}]}]}',
        encoding="utf-8",
    )

    loaded = FinalPackageLoader().load(package, tmp_path / "work")

    assert loaded.semantic_bindings["schema_name"] == "HEXA_ASSET_LEVEL_SEMANTIC_BINDINGS"
    assert loaded.semantic_bindings["scenes"][0]["assets"][1]["sequence_order"] == 2


def test_rejects_asset_level_group_membership_mismatch(tmp_path: Path) -> None:
    package = tmp_path / "package"
    scenes = package / "scenes"
    scenes.mkdir(parents=True)
    (scenes / "SCENE_001.png").write_bytes(b"png")
    (package / "canonical_script.txt").write_text("alpha beta", encoding="utf-8")
    (package / "semantic_bindings.json").write_text(
        '{"schema_name":"HEXA_ASSET_LEVEL_SEMANTIC_BINDINGS","scenes":['
        '{"scene_id":"SCENE_001","semantic_groups":['
        '{"semantic_group_id":"g","script_text":"alpha beta",'
        '"animation_policy":"SEQUENTIAL_WITHIN_PHRASE",'
        '"asset_ids":["intent-a"]}],"assets":['
        '{"asset_id":"intent-a","script_text":"alpha beta",'
        '"binding_type":"EXPLICIT","semantic_group_id":"other",'
        '"sequence_order":1,"confidence":1.0,"parent_asset_id":null}]}]}',
        encoding="utf-8",
    )

    with pytest.raises(InvalidPackageError, match="membership mismatch"):
        FinalPackageLoader().load(package, tmp_path / "work")
