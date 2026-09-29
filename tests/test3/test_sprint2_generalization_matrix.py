from __future__ import annotations

import pytest

from tests.test1.certification.test_generated_full_layer_matrix import _plan
from tests.test1.factory import DiskPackageShape, seeded_disk_shape
from tests.test2.support.sprint2_perceptual_oracle import (
    assert_sprint2_perceptual_contracts,
)


SPRINT2_GENERALIZATION_SEEDS = tuple(range(8101, 8181))


@pytest.mark.parametrize("seed", SPRINT2_GENERALIZATION_SEEDS)
def test_seeded_packages_preserve_sprint2_perceptual_contracts(
    tmp_path,
    seed: int,
) -> None:
    result = _plan(tmp_path, seeded_disk_shape(seed))
    canonical, story, _choreography, composition, motion, _text, plan = result
    assert_sprint2_perceptual_contracts(
        canonical,
        story,
        composition,
        motion,
        plan,
    )


FIXED_SPRINT2_SHAPES = (
    (
        "single-minimal",
        DiskPackageShape(
            scenes=1,
            assets_per_scene=1,
            relations=False,
            dependencies=False,
        ),
    ),
    (
        "dense-20-arabic",
        DiskPackageShape(
            scenes=1,
            assets_per_scene=20,
            locators="partial",
            group_count=2,
            script_style="arabic",
        ),
    ),
    (
        "dense-20-numbers",
        DiskPackageShape(
            scenes=1,
            assets_per_scene=20,
            locators="all",
            group_count=2,
            script_style="numbers",
        ),
    ),
    (
        "branching-reuse",
        DiskPackageShape(
            scenes=8,
            assets_per_scene=6,
            dependency_mode="branching",
            reuse_first_asset=True,
            script_style="arabic",
        ),
    ),
    (
        "simultaneous-units",
        DiskPackageShape(
            scenes=3,
            assets_per_scene=6,
            group_count=2,
            group_policy="SIMULTANEOUS_VISUAL_UNIT",
        ),
    ),
    (
        "compound-arabic",
        DiskPackageShape(
            scenes=3,
            assets_per_scene=5,
            compound=True,
            script_style="arabic",
        ),
    ),
    (
        "numbers-persist",
        DiskPackageShape(
            scenes=3,
            assets_per_scene=5,
            script_style="numbers",
            continuity="persist",
            reuse_first_asset=True,
        ),
    ),
    (
        "transform-continuity",
        DiskPackageShape(
            scenes=3,
            assets_per_scene=5,
            continuity="transform",
            reuse_first_asset=True,
        ),
    ),
    (
        "no-progression-no-locators",
        DiskPackageShape(
            scenes=4,
            assets_per_scene=5,
            progression=False,
            locators="none",
        ),
    ),
    (
        "support-bindings",
        DiskPackageShape(
            scenes=2,
            assets_per_scene=5,
            binding_types=("EXPLICIT", "SUPPORT"),
        ),
    ),
    (
        "ambiguous-bindings",
        DiskPackageShape(
            scenes=2,
            assets_per_scene=5,
            binding_types=("SEMANTIC", "AMBIGUOUS"),
        ),
    ),
    (
        "parent-bindings",
        DiskPackageShape(
            scenes=2,
            assets_per_scene=5,
            binding_types=("EXPLICIT", "PARENT", "SEMANTIC"),
            compound=True,
        ),
    ),
)


@pytest.mark.parametrize(
    ("case_name", "shape"),
    FIXED_SPRINT2_SHAPES,
    ids=[row[0] for row in FIXED_SPRINT2_SHAPES],
)
def test_fixed_final_package_patterns_preserve_sprint2_perceptual_contracts(
    tmp_path,
    case_name: str,
    shape: DiskPackageShape,
) -> None:
    result = _plan(tmp_path / case_name, shape)
    canonical, story, _choreography, composition, motion, _text, plan = result
    assert_sprint2_perceptual_contracts(
        canonical,
        story,
        composition,
        motion,
        plan,
    )