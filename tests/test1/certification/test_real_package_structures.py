from __future__ import annotations

import os
import zipfile
from dataclasses import dataclass
from pathlib import Path

import pytest

from app.final_package import FinalPackageLoader

@dataclass(frozen=True, slots=True)
class _ExpectedPackage:
    sha256: str
    scenes: int
    objects: int
    renderable_assets: int
    groups: int
    events: int
    relations: int
    visual_progression: int
    timing_authority: str


_EXPECTED = {
    "HEXA_BLACK_HAT_HACKER_AR_UNIFIED_FINAL_PACKAGE_2_0.zip": _ExpectedPackage(
        sha256="bfb64814b1fcdb952e2c93216822f49ba651e7fb113079aa8ee40cdeca53630f",
        scenes=40, objects=129, renderable_assets=129, groups=40, events=55,
        relations=15, visual_progression=0,
        timing_authority="FINAL_VOICE_OVER_SEPARATE_INPUT",
    ),
    "HEXA_WHITE_HAT_HACKER_AR_UNIFIED_FINAL_PACKAGE_2_0.zip": _ExpectedPackage(
        sha256="58af4ea62a854076c6550b33a1db7b821a1f8cd0288d41337a98e1af4ca6ecd5",
        scenes=35, objects=215, renderable_assets=145, groups=35, events=51,
        relations=16, visual_progression=35, timing_authority="FINAL_VOICE_OVER",
    ),
    # Gray Hat, Script Kiddie and Hacktivist carry artwork-measured visual_locator
    # repairs (semantics, events, groups and relations unchanged) so every required
    # carrier and all authored artwork are provable by the carrier/hidden-art gates.
    "HEXA_GRAY_HAT_HACKER_AR_UNIFIED_FINAL_PACKAGE_2_0.zip": _ExpectedPackage(
        sha256="b51958adc787ec311f3c5ed1b38318a0b2f7b06878b9a863246486a1e66068ed",
        scenes=35, objects=194, renderable_assets=135, groups=35, events=75,
        relations=35, visual_progression=0, timing_authority="FINAL_VOICE_OVER",
    ),
    "HEXA_SCRIPT_KIDDIE_AR_UNIFIED_FINAL_PACKAGE_2_0.zip": _ExpectedPackage(
        sha256="3527c14399e8de5a255cd5a0d055b38848494e0bfd0815ca5bd9b4ea2c816561",
        scenes=35, objects=80, renderable_assets=80, groups=80, events=80,
        relations=0, visual_progression=0,
        timing_authority="FINAL_VOICE_OVER_SEPARATE_INPUT",
    ),
    "HEXA_HACKTIVIST_AR_UNIFIED_FINAL_PACKAGE_2_0.zip": _ExpectedPackage(
        sha256="2bfe6b78b4ac2889d05e32bd52dcee18f412f1f40630591216b122b8bd9c7285",
        scenes=26, objects=62, renderable_assets=62, groups=62, events=62,
        relations=0, visual_progression=0,
        timing_authority="FINAL_VOICE_OVER_SEPARATE_INPUT",
    ),
    "HEXA_STATE_LINKED_GROUP_AR_UNIFIED_FINAL_PACKAGE_2_0.zip": _ExpectedPackage(
        sha256="7ad3675d64f790d6752963064184f85552668656e8837456bea9988440cfea8c",
        scenes=27, objects=111, renderable_assets=111, groups=27, events=27,
        relations=0, visual_progression=0,
        timing_authority="FINAL_VOICE_OVER_SEPARATE_INPUT",
    ),
}


def _corpus_root() -> Path:
    corpus = os.getenv("HEXA_REAL_PACKAGE_CORPUS")
    if not corpus:
        if os.getenv("HEXA_REQUIRE_REAL_PACKAGE_CORPUS") == "1":
            pytest.fail("REAL PACKAGE CERTIFICATION BLOCKED: HEXA_REAL_PACKAGE_CORPUS is unset")
        pytest.skip("real Final Package corpus is not installed in this CI environment")
    return Path(corpus)


@pytest.mark.parametrize("filename,expected", _EXPECTED.items())
def test_real_corrected_package_corpus(
    tmp_path: Path, filename: str, expected: _ExpectedPackage,
) -> None:
    source = _corpus_root() / filename
    if not source.is_file():
        pytest.fail(f"missing certified Final Package fixture: {source}")

    assert FinalPackageLoader.package_sha256(source) == expected.sha256
    with zipfile.ZipFile(source) as archive:
        file_names = [name for name in archive.namelist() if not name.endswith("/")]
        assert "package.json" in file_names
        assert len([name for name in file_names if name.startswith("images/")]) == expected.scenes
        assert all(name == "package.json" or name.startswith("images/") for name in file_names)
        assert not {Path(name).name for name in file_names} & {
            "manifest.json", "scene_plan.json", "semantic_bindings.json"
        }

    canonical = FinalPackageLoader().load(source, tmp_path / filename.removesuffix(".zip"))
    assert canonical.contract_name == "HEXA_UNIFIED_FINAL_PACKAGE"
    assert canonical.contract_version == "2.0"
    assert canonical.builder_target == "HEXA_VIDEO_BUILDER_V20"
    assert canonical.script_audio_relationship == "EXACT_MATCH"
    assert canonical.timing_authority == expected.timing_authority
    assert len(canonical.scenes) == expected.scenes
    assert sum(len(scene.units) for scene in canonical.scenes) == expected.objects
    assert len(canonical.asset_by_id) == expected.renderable_assets
    assert sum(len(scene.semantic_groups) for scene in canonical.scenes) == expected.groups
    assert len(canonical.event_by_id) == expected.events
    assert sum(len(scene.relations) for scene in canonical.scenes) == expected.relations
    assert sum(len(scene.visual_progression) for scene in canonical.scenes) == expected.visual_progression


def test_script_kiddie_zero_relations_is_authoritative_source_truth(tmp_path: Path) -> None:
    filename = "HEXA_SCRIPT_KIDDIE_AR_UNIFIED_FINAL_PACKAGE_2_0.zip"
    source = _corpus_root() / filename
    if not source.is_file():
        pytest.fail(f"missing certified Final Package fixture: {source}")
    canonical = FinalPackageLoader().load(source, tmp_path / "script-kiddie")
    assert all(scene.relations == () for scene in canonical.scenes)
    assert len(canonical.event_by_id) == 80


def test_real_corpus_preserves_white_and_gray_typed_semantic_linkage(tmp_path: Path) -> None:
    corpus = _corpus_root()
    white = FinalPackageLoader().load(
        corpus / "HEXA_WHITE_HAT_HACKER_AR_UNIFIED_FINAL_PACKAGE_2_0.zip",
        tmp_path / "white",
    )
    source_links = [
        asset.source_asset_id
        for scene in white.scenes
        for asset in scene.assets
        if asset.source_asset_id is not None
    ]
    progression = [row for scene in white.scenes for row in scene.visual_progression]
    assert len(source_links) == 145
    assert len(progression) == 35
    assert all(row.event_id is not None and row.order is not None for row in progression)

    gray = FinalPackageLoader().load(
        corpus / "HEXA_GRAY_HAT_HACKER_AR_UNIFIED_FINAL_PACKAGE_2_0.zip",
        tmp_path / "gray",
    )
    relations = [row for scene in gray.scenes for row in scene.relations]
    assert sum(row.relation_id is not None for row in relations) == 13
    assert sum(row.connector_asset_id is not None for row in relations) == 5


def test_committed_corpus_manifest_matches_certified_fingerprints() -> None:
    """The CI corpus manifest and these fingerprints must describe the same bytes."""
    from tests.support.real_corpus import certified_packages

    assert certified_packages() == {
        filename: expected.sha256 for filename, expected in _EXPECTED.items()
    }