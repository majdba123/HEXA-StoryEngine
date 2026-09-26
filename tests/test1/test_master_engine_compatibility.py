from pathlib import Path

from app.canonical import CanonicalNormalizer
from tests.test1.factory import make_package


def test_master_canonical_compatibility_matrix(tmp_path: Path) -> None:
    checked = 0
    for seed in range(2001, 2121):
        package = make_package(
            tmp_path / str(seed), seed=seed,
            scene_count=1 + seed % 5,
            assets_per_scene=1 + seed % 10,
            events_per_scene=1 + seed % 5,
            with_relations=seed % 2 == 0,
            with_locators=seed % 4 != 0,
            optional_metadata=seed % 3 == 0,
        )
        canonical = CanonicalNormalizer().normalize(package)
        assert canonical.scenes
        assert canonical.asset_by_id
        checked += 1
    assert checked == 120
