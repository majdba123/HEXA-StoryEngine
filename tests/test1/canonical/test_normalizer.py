from pathlib import Path

from app.canonical import BindingType, CanonicalNormalizer, VisualFocus
from tests.test1.factory import make_package


def test_normalizer_preserves_semantic_counts_and_identity(tmp_path: Path) -> None:
    package = make_package(tmp_path, scene_count=4, assets_per_scene=5, events_per_scene=3)
    canonical = CanonicalNormalizer().normalize(package)
    assert len(canonical.scenes) == 4
    assert len(canonical.asset_by_id) == 20
    assert len(canonical.event_by_id) == 12
    assert set(canonical.asset_by_id) == {
        asset["asset_id"]
        for scene in package.semantic_bindings["scenes"]
        for asset in scene["assets"]
    }


def test_closed_domains_are_normalized_to_enums(tmp_path: Path) -> None:
    package = make_package(tmp_path, scene_count=1, assets_per_scene=1, events_per_scene=1)
    package.semantic_bindings["scenes"][0]["assets"][0]["binding_type"] = "explicit"
    package.semantic_bindings["scenes"][0]["assets"][0]["visual_focus"] = "primary"
    canonical = CanonicalNormalizer().normalize(package)
    asset = next(iter(canonical.asset_by_id.values()))
    assert asset.binding_type is BindingType.EXPLICIT
    assert asset.visual_focus is VisualFocus.PRIMARY


def test_optional_metadata_does_not_change_semantic_signature(tmp_path: Path) -> None:
    a = CanonicalNormalizer().normalize(make_package(tmp_path / "a", seed=42, optional_metadata=False))
    b = CanonicalNormalizer().normalize(make_package(tmp_path / "b", seed=42, optional_metadata=True))
    sig_a = [(s.id, [(x.asset_id, x.semantic_event_id, x.binding_type) for x in s.assets]) for s in a.scenes]
    sig_b = [(s.id, [(x.asset_id, x.semantic_event_id, x.binding_type) for x in s.assets]) for s in b.scenes]
    assert sig_a == sig_b
