from __future__ import annotations

from collections.abc import Mapping

import pytest
from pydantic import ValidationError

from app.canonical import CanonicalAsset, CanonicalPackage, CanonicalScene


def _package(tmp_path):
    asset = CanonicalAsset(
        unit_id="A1",
        asset_id="A1",
        scene_id="S1",
        visual_state={"before": "SAFE", "after": "CHANGED"},
        extension_metadata={
            "nested": {"items": [1, 2, {"flag": True}]},
        },
    )
    scene = CanonicalScene(
        id="S1",
        image_path=tmp_path / "scene.png",
        order=0,
        units=(asset,),
        extension_metadata={"labels": ["a", "b"]},
    )
    return CanonicalPackage(
        root=tmp_path,
        package_id="immutable",
        scenes=(scene,),
        extension_metadata={"outer": {"enabled": True}},
    )


def test_canonical_records_are_not_mapping_compatibility_objects(tmp_path) -> None:
    package = _package(tmp_path)
    asset = package.scenes[0].assets[0]

    assert not isinstance(asset, Mapping)
    assert not hasattr(asset, "get")
    with pytest.raises(TypeError):
        _ = asset["asset_id"]  # type: ignore[index]


def test_canonical_semantic_truth_is_deeply_immutable(tmp_path) -> None:
    package = _package(tmp_path)
    asset = package.scenes[0].assets[0]

    with pytest.raises(ValidationError):
        asset.role = "changed"  # type: ignore[misc]
    with pytest.raises(TypeError):
        asset.visual_state["before"] = "BROKEN"  # type: ignore[index]
    with pytest.raises(TypeError):
        asset.extension_metadata["nested"]["x"] = 1  # type: ignore[index]

    items = asset.extension_metadata["nested"]["items"]
    assert isinstance(items, tuple)
    with pytest.raises(AttributeError):
        items.append(3)  # type: ignore[attr-defined]

    with pytest.raises(TypeError):
        package.extension_metadata["outer"]["enabled"] = False  # type: ignore[index]
