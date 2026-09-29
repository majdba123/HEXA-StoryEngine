from pathlib import Path

import pytest

from app.final_package import FinalPackageLoader
from tests.test1.factory import seeded_disk_shape, write_valid_package


@pytest.mark.parametrize("seed", range(3001, 3121))
def test_generated_packages_cross_real_boundary_before_canonicalization(
    tmp_path: Path, seed: int
) -> None:
    shape = seeded_disk_shape(seed)
    source = write_valid_package(tmp_path / f"source-{seed}", shape)
    raw = FinalPackageLoader().load(source, tmp_path / f"work-{seed}")
    canonical = raw

    assert len(canonical.scenes) == shape.scenes
    assert len(canonical.asset_by_id) == shape.scenes * shape.assets_per_scene
    assert len(canonical.event_by_id) == shape.scenes * shape.assets_per_scene
