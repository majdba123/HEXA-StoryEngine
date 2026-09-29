from __future__ import annotations

from time import perf_counter

from app.final_package import FinalPackageLoader
from tests.test1.factory import DiskPackageShape, write_valid_package


def test_large_unified_canonicalization_has_no_combinatorial_explosion(tmp_path) -> None:
    source = write_valid_package(
        tmp_path / "source",
        DiskPackageShape(
            scenes=50,
            assets_per_scene=20,
            relations=True,
            dependencies=True,
            dependency_mode="linear",
            locators="none",
            progression=True,
            group_count=2,
            extra_metadata=True,
            namespace="PERF",
        ),
    )
    raw = FinalPackageLoader().load(source, tmp_path / "work")

    started = perf_counter()
    canonical = raw
    elapsed = perf_counter() - started

    assert len(canonical.scenes) == 50
    assert len(canonical.asset_by_id) == 1000
    assert len(canonical.event_by_id) == 1000
    # This is deliberately generous and is not a microbenchmark. It only catches
    # accidental quadratic/combinatorial regressions in normalization.
    assert elapsed < 10.0
