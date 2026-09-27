from __future__ import annotations
# Owner-scoped Test2 coverage; historical regression content is preserved.

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from typing import get_type_hints

import pytest

from app.canonical import CanonicalAsset, CanonicalPackage, CanonicalScene
from app.pipeline import StoryEnginePipeline


class _RefinementSpy:
    def __init__(self, result: list[object]) -> None:
        self.calls: list[tuple] = []
        self.result = result

    def refine(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.result


def _package(tmp_path: Path) -> CanonicalPackage:
    return CanonicalPackage(
        root=tmp_path,
        package_id="typed-refinement",
        scenes=(
            CanonicalScene(
                id="SCENE_001",
                image_path=tmp_path / "scene.png",
                order=0,
                units=(
                    CanonicalAsset(
                        unit_id="A1",
                        asset_id="A1",
                        scene_id="SCENE_001",
                        type="VISUAL_ASSET_INTENT",
                    ),
                    CanonicalAsset(
                        unit_id="T1",
                        asset_id="T1",
                        scene_id="SCENE_001",
                        type="TEXT_INTENT",
                    ),
                ),
            ),
        ),
    )


def _pipeline(mode: str, pass2: _RefinementSpy, legacy: _RefinementSpy):
    pipeline = StoryEnginePipeline.__new__(StoryEnginePipeline)
    pipeline.settings = SimpleNamespace(refinement_mode=mode)
    pipeline.cutout_pass2 = pass2
    pipeline.refinement = legacy
    return pipeline


def test_apply_refinement_declares_typed_canonical_contract() -> None:
    assert get_type_hints(StoryEnginePipeline._apply_refinement)["package"] is CanonicalPackage


@pytest.mark.parametrize("mode", ["vnext", "pass2_vnext", "hybrid"])
def test_typed_canonical_assets_are_dispatched_to_pass2_without_mapping_access(
    tmp_path: Path,
    mode: str,
) -> None:
    package = _package(tmp_path)
    snapshot = deepcopy(package.model_dump())
    assets = [object(), object()]
    output = [object(), object()]
    pass2 = _RefinementSpy(output)
    legacy = _RefinementSpy([])

    actual = _pipeline(mode, pass2, legacy)._apply_refinement(package, assets, tmp_path)

    assert actual is output
    assert legacy.calls == []
    assert pass2.calls == [(
        (assets, tmp_path),
        {"scene_unit_types": {"SCENE_001": ["VISUAL_ASSET_INTENT", "TEXT_INTENT"]}},
    )]
    assert package.model_dump() == snapshot


@pytest.mark.parametrize("mode", ["off", "pass1", "disabled"])
def test_refinement_disabled_modes_preserve_input_identity_and_call_no_service(
    tmp_path: Path,
    mode: str,
) -> None:
    package = _package(tmp_path)
    assets = [object(), object()]
    pass2 = _RefinementSpy([])
    legacy = _RefinementSpy([])

    actual = _pipeline(mode, pass2, legacy)._apply_refinement(package, assets, tmp_path)

    assert actual is assets
    assert pass2.calls == []
    assert legacy.calls == []


@pytest.mark.parametrize("mode", ["legacy", "default", "unknown"])
def test_supported_legacy_dispatch_uses_only_legacy_service(
    tmp_path: Path,
    mode: str,
) -> None:
    package = _package(tmp_path)
    assets = [object(), object()]
    output = [object()]
    pass2 = _RefinementSpy([])
    legacy = _RefinementSpy(output)

    actual = _pipeline(mode, pass2, legacy)._apply_refinement(package, assets, tmp_path)

    assert actual is output
    assert pass2.calls == []
    assert legacy.calls == [((assets, tmp_path), {})]
