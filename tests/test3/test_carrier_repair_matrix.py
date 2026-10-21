"""Repair instead of stopping, certified on every defect family of the strict suites.

tests/certification/semantic_carrier certifies that each defect stops with its typed code
(strict mode). In production (repair mode) the same defects must end in exactly one of two
ways: a plan in which every repaired cutout is visible, no significant authored cutout is
hidden, and every downstream layer reaches a RenderPlan; or the same typed stop (a defect
no visible repair can answer). Never a crash, another code, or a half plan.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.choreography import ChoreographyDirector
from app.composition import CompositionPlanner
from app.motion import MotionPlanner
from app.render import RenderPlanner
from app.shared.errors import StageFailedError
from app.story import StoryPlanner
from app.text import TextPlanner
from tests.certification.semantic_carrier import cases as C
from tests.support.carrier_matrix import generate_case
from tests.support.carrier_scene import build_package

FAILURES = [(family, seed) for family in sorted(C.FAILURE_FAMILIES) for seed in range(0, 25, 6)]
MUST_FAIL_MUTATIONS = ("shift_locator_far", "merge_cutouts", "remove_cutout", "equal_score_candidates")
MUTATED = [(mutation, seed) for mutation in MUST_FAIL_MUTATIONS for seed in range(0, 15, 4)]
PACKAGE_SHAPES = [seed for seed in range(9000, 9040, 4)]


def _repaired_or_typed(built, expected: set[str], tmp_path: Path) -> str:
    planner = StoryPlanner()
    try:
        story = planner.plan(built.package, built.transcript, built.assets)
    except StageFailedError as error:
        assert error.effective_code in expected, error.effective_code
        return "typed"
    visible = {asset_id for beat in story for asset_id in (beat.active_visual_semantic_state or {})}
    assert {row["asset_id"] for row in planner.carrier_repairs} <= visible
    assert planner.hidden_content_audit == []
    choreography = ChoreographyDirector().plan(built.package, story, built.assets)
    composition = CompositionPlanner().plan(story, built.assets, choreography)
    motion = MotionPlanner().plan(story, composition, choreography, built.assets)
    text = TextPlanner().plan(transcript=built.transcript, story=story, assets=built.assets,
                              package=built.package, choreography=choreography)
    (tmp_path / "render").mkdir(parents=True)
    _plan, path = RenderPlanner().compile(built.transcript, built.assets, story, composition, motion,
                                          tmp_path / "render", text=text)
    assert path.is_file()
    return "repaired"


@pytest.mark.parametrize(("family", "seed"), FAILURES)
def test_certified_defect_is_repaired_or_keeps_its_typed_stop(tmp_path: Path, family: str, seed: int) -> None:
    case = C.failure(family, seed)
    built = build_package([case.spec], namespace="CERT", image_root=tmp_path / "images", write_images=True)
    expected = {case.expected_code, "SEMANTIC_CARRIER_AMBIGUOUS"}
    _repaired_or_typed(built, expected, tmp_path)


@pytest.mark.parametrize(("mutation", "seed"), MUTATED)
def test_must_stop_mutation_is_repaired_or_keeps_its_typed_stop(tmp_path: Path, mutation: str, seed: int) -> None:
    case = C.mutate(mutation, seed)
    built = build_package([case.spec], namespace="CERT", image_root=tmp_path / "images", write_images=True)
    expected = {"SEMANTIC_CARRIER_UNRESOLVED", "SEMANTIC_CARRIER_AMBIGUOUS", "AUTHORED_CONTENT_HIDDEN"}
    _repaired_or_typed(built, expected, tmp_path)


@pytest.mark.parametrize("seed", PACKAGE_SHAPES)
def test_defective_package_shape_is_repaired_or_keeps_its_typed_stop(tmp_path: Path, seed: int) -> None:
    case = generate_case(seed, negative=True)
    built = build_package(list(case.scenes), namespace=f"NR{seed}", image_root=tmp_path / "images",
                          write_images=True)
    _repaired_or_typed(built, {case.expected_code}, tmp_path)


def test_most_certified_defects_are_repaired_not_stopped(tmp_path: Path) -> None:
    """The point of the policy: across the defect families, a stop is the exception."""
    outcomes = []
    for index, (family, seed) in enumerate(FAILURES):
        case = C.failure(family, seed)
        built = build_package([case.spec], namespace="CERT", image_root=tmp_path / f"i{index}", write_images=True)
        outcomes.append(_repaired_or_typed(built, {case.expected_code, "SEMANTIC_CARRIER_AMBIGUOUS"},
                                           tmp_path / f"w{index}"))
    assert outcomes.count("repaired") >= len(outcomes) * 0.6, outcomes
