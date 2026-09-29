from pathlib import Path

import pytest

from tests.test1.factory import make_package


@pytest.mark.parametrize("seed", range(1001, 1121))
def test_generated_valid_topologies_normalize_without_unclassified_exceptions(
    tmp_path: Path, seed: int
) -> None:
    package = make_package(
        tmp_path / str(seed),
        seed=seed,
        scene_count=1 + seed % 7,
        assets_per_scene=1 + seed % 8,
        events_per_scene=1 + seed % 4,
        with_relations=bool(seed % 2),
        with_locators=bool(seed % 3),
        optional_metadata=bool(seed % 5),
    )
    canonical = package
    assert canonical.package_id == package.package_id
    assert len(canonical.scenes) == len(package.scenes)
    assert len(canonical.asset_by_id) == len(package.scenes) * (1 + seed % 8)
    assert len(canonical.event_by_id) == len(package.scenes) * (1 + seed % 4)
