from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from PIL import Image

from app.final_package import FinalPackageLoader
from app.shared.errors import InvalidPackageError
from tests.support.unified_package import write_unified_package


TARGET = (1920, 1080)


def _locator(cx: float = 0.5, cy: float = 0.5, width: float = 0.2, height: float = 0.2) -> dict:
    return {"coordinate_space": "normalized_scene", "cx": cx, "cy": cy, "width": width, "height": height}


def _package(tmp_path: Path, size: tuple[int, int], *, locators: list[dict | None] | None = None, scenes: int = 1) -> Path:
    locators = [_locator()] if locators is None else locators
    rows = []
    for scene_index in range(scenes):
        scene_id = f"SCENE_{scene_index + 1:03d}"
        objects = [
            {"asset_id": f"asset-{scene_index}-{index}", "visual_locator": locator}
            for index, locator in enumerate(locators)
        ]
        rows.append({"scene_id": scene_id, "objects": objects})
    root = write_unified_package(tmp_path / "source", script="alpha", scenes=rows, image_size=TARGET)
    for index in range(scenes):
        if index == 0 or scenes == 1:
            Image.new("RGB", size, "black").save(root / "images" / f"SCENE_{index + 1:03d}.png")
    return root


def _load(source: Path, workspace: Path):
    return FinalPackageLoader().load(source, workspace)


def _diagnostics(workspace: Path) -> dict:
    return json.loads((workspace / "diagnostics" / "image-contract-repair.json").read_text(encoding="utf-8"))


def test_exact_image_is_not_rewritten(tmp_path: Path) -> None:
    source = _package(tmp_path, TARGET)
    original = (source / "images" / "SCENE_001.png").read_bytes()
    workspace = tmp_path / "work"
    package = _load(source, workspace)
    assert package.scenes[0].image_path.read_bytes() == original
    assert _diagnostics(workspace)["scenes"][0]["repair_type"] == "UNCHANGED"


@pytest.mark.parametrize("size", [(1280, 720), (1024, 576), (3840, 2160)])
def test_same_aspect_resolution_is_resized(tmp_path: Path, size: tuple[int, int]) -> None:
    workspace = tmp_path / "work"
    package = _load(_package(tmp_path, size), workspace)
    with Image.open(package.scenes[0].image_path) as repaired:
        assert repaired.size == TARGET
    assert _diagnostics(workspace)["scenes"][0]["repair_type"] == "RESIZED_SAME_ASPECT"


@pytest.mark.parametrize(
    ("size", "expected_padding"),
    [((1024, 1024), (420, 0)), ((1080, 1920), (656, 0)), ((2400, 900), (0, 180))],
)
def test_different_aspect_is_contained_on_white(tmp_path: Path, size: tuple[int, int], expected_padding: tuple[int, int]) -> None:
    workspace = tmp_path / "work"
    package = _load(_package(tmp_path, size), workspace)
    with Image.open(package.scenes[0].image_path) as repaired:
        assert repaired.size == TARGET
        assert repaired.getpixel((0, 0)) == (255, 255, 255)
    row = _diagnostics(workspace)["scenes"][0]
    assert row["repair_type"] == "FIT_PAD_AND_REMAP_LOCATORS"
    assert (row["padding_x"], row["padding_y"]) == expected_padding


@pytest.mark.parametrize(
    ("size", "expected"),
    [((1024, 1024), (0.5, 0.5, 0.1125, 0.2)), ((2400, 900), (0.5, 0.5, 0.2, 2 / 15))],
)
def test_locator_is_remapped_through_padding(tmp_path: Path, size: tuple[int, int], expected: tuple[float, ...]) -> None:
    package = _load(_package(tmp_path, size), tmp_path / "work")
    locator = package.scenes[0].units[0].visual_locator
    assert locator is not None
    assert (locator.cx, locator.cy, locator.width, locator.height) == pytest.approx(expected)


def test_multiple_locators_are_remapped(tmp_path: Path) -> None:
    locators = [_locator(0.2, 0.3, 0.2, 0.2), _locator(0.8, 0.75, 0.3, 0.4)]
    package = _load(_package(tmp_path, (1024, 1024), locators=locators), tmp_path / "work")
    mapped = [unit.visual_locator for unit in package.scenes[0].units]
    assert all(locator is not None for locator in mapped)
    assert mapped[0].cx == pytest.approx(0.33125)
    assert mapped[0].cy == pytest.approx(0.3)
    assert mapped[1].cx == pytest.approx(0.66875)


def test_locator_on_source_boundary_remains_valid(tmp_path: Path) -> None:
    package = _load(
        _package(tmp_path, (1024, 1024), locators=[_locator(0.1, 0.1, 0.2, 0.2)]),
        tmp_path / "work",
    )
    locator = package.scenes[0].units[0].visual_locator
    assert locator is not None
    assert locator.cx == pytest.approx(0.275)
    assert locator.cy == pytest.approx(0.1)


def test_absent_locator_needs_no_invention(tmp_path: Path) -> None:
    package = _load(_package(tmp_path, (1024, 1024), locators=[None]), tmp_path / "work")
    assert package.scenes[0].units[0].visual_locator is None


def test_corrupt_image_fails_with_typed_repair_error(tmp_path: Path) -> None:
    source = _package(tmp_path, (1024, 1024))
    (source / "images" / "SCENE_001.png").write_bytes(b"not an image")
    with pytest.raises(InvalidPackageError, match="unsafe scene image") as caught:
        _load(source, tmp_path / "work")
    assert caught.value.effective_code == "IMAGE_CONTRACT_REPAIR_FAILED"
    assert caught.value.details["repair_type"] == "REJECTED_UNSAFE_IMAGE"


def test_invalid_dimensions_fail_before_repair(tmp_path: Path) -> None:
    source = _package(tmp_path, TARGET)
    path = source / "package.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["image_spec"]["width"] = 0
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(InvalidPackageError, match="dimensions must be positive"):
        _load(source, tmp_path / "work")


def test_only_mismatching_scene_is_rewritten(tmp_path: Path) -> None:
    source = _package(tmp_path, (1024, 576), scenes=2)
    valid_source_bytes = (source / "images" / "SCENE_002.png").read_bytes()
    workspace = tmp_path / "work"
    package = _load(source, workspace)
    assert package.scenes[1].image_path.read_bytes() == valid_source_bytes
    assert [row["repair_type"] for row in _diagnostics(workspace)["scenes"]] == [
        "RESIZED_SAME_ASPECT",
        "UNCHANGED",
    ]


def test_raw_dimension_failure_is_repaired_then_strictly_validated(tmp_path: Path) -> None:
    source = _package(tmp_path, (1024, 576))
    loader = FinalPackageLoader()
    raw = loader._load_payload(source / "package.json")
    with pytest.raises(InvalidPackageError, match="scene image dimensions do not match image_spec"):
        loader._validate_payload(raw, source)
    package = loader.load(source, tmp_path / "work")
    loader._validate_payload(loader._load_payload(package.root / "package.json"), package.root)


def test_source_is_immutable(tmp_path: Path) -> None:
    source = _package(tmp_path, (1024, 1024), locators=[_locator(0.25, 0.4, 0.2, 0.3)])
    source_hashes = {
        path.relative_to(source): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in source.rglob("*")
        if path.is_file()
    }
    _load(source, tmp_path / "work")
    after_hashes = {
        path.relative_to(source): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in source.rglob("*")
        if path.is_file()
    }
    assert after_hashes == source_hashes


def test_repair_is_deterministic_across_workspaces(tmp_path: Path) -> None:
    source = _package(tmp_path, (1024, 1024), locators=[_locator(0.25, 0.4, 0.2, 0.3)])
    first = _load(source, tmp_path / "work-1")
    second = _load(source, tmp_path / "work-2")
    assert first.scenes[0].image_path.read_bytes() == second.scenes[0].image_path.read_bytes()
    assert (first.root / "package.json").read_bytes() == (second.root / "package.json").read_bytes()
