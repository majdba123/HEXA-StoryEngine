from pathlib import Path

from app.canonical import BindingType, VisualFocus
from app.final_package import FinalPackageLoader
from tests.test1.factory import DiskPackageShape, make_package, write_valid_package


def test_unified_loader_preserves_semantic_counts_and_identity(tmp_path: Path) -> None:
    package = make_package(tmp_path, scene_count=4, assets_per_scene=5, events_per_scene=3)
    assert len(package.scenes) == 4
    assert len(package.asset_by_id) == 20
    assert len(package.event_by_id) == 12
    assert len(set(package.asset_by_id)) == 20


def test_unified_loader_maps_closed_domains_to_enums(tmp_path: Path) -> None:
    source = write_valid_package(
        tmp_path / "source",
        DiskPackageShape(scenes=1, assets_per_scene=1, locators="all"),
    )
    import json

    path = source / "package.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["scenes"][0]["objects"][0]["binding_type"] = "explicit"
    payload["scenes"][0]["objects"][0]["visual_focus"] = "primary"
    path.write_text(json.dumps(payload), encoding="utf-8")
    package = FinalPackageLoader().load(source, tmp_path / "work")
    asset = next(iter(package.asset_by_id.values()))
    assert asset.binding_type is BindingType.EXPLICIT
    assert asset.visual_focus is VisualFocus.PRIMARY


def test_optional_metadata_does_not_change_semantic_signature(tmp_path: Path) -> None:
    a = make_package(tmp_path / "a", seed=42, optional_metadata=False)
    b = make_package(tmp_path / "b", seed=42, optional_metadata=True)
    sig_a = [(s.id, [(x.asset_id, x.semantic_event_id, x.binding_type) for x in s.assets]) for s in a.scenes]
    sig_b = [(s.id, [(x.asset_id, x.semantic_event_id, x.binding_type) for x in s.assets]) for s in b.scenes]
    assert sig_a == sig_b
