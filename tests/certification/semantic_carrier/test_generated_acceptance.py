"""LAYERS 3 + 4 - generated package-shaped acceptance and mutation certification.

866 seeded cases with ground truth:
  252 clean positive   (12 families x 21 seeds)  correct owner for every unit
  204 complex positive (12 families x 17 seeds)  groups, shared carriers, dense scenes
  200 expected failure ( 8 families x 25 seeds)  typed failure before FFmpeg
  210 mutation         (14 mutations x 15 seeds) one change: correct mapping or typed fail
All 456 positives run through Story; 114 of them through RenderPlan; 100 cases are
resolved 10 times each and 456 are re-resolved under shuffled input order.
"""

from __future__ import annotations

import dataclasses
import random
from pathlib import Path

import pytest

from app.story.carrier_resolver import CarrierConfidence, SemanticCarrierResolver
from tests.support.carrier_scene import Cutout, Unit, build_package

from . import cases as C
from .verdict import TYPED_FAILURES, fingerprint, mismatches, run_render_plan, run_story

CLEAN = [(family, seed) for family in C.CLEAN_FAMILIES for seed in range(21)]
COMPLEX = [(family, seed) for family in C.COMPLEX_FAMILIES for seed in range(17)]
FAILURES = [(family, seed) for family in C.FAILURE_FAMILIES for seed in range(25)]
MUTATED = [(mutation, seed) for mutation in C.MUTATIONS for seed in range(15)]
POSITIVE = CLEAN + COMPLEX
RENDER_PLAN = POSITIVE[::4]
REPRODUCIBILITY = (POSITIVE[::5] + MUTATED[::10])[:100]
REPRODUCIBILITY_RUNS = 10

# What each single mutation must produce: the correct mapping, or this typed failure.
MUTATION_MUST_FAIL = {
    "shift_locator_far": {"SEMANTIC_CARRIER_UNRESOLVED", "AUTHORED_CONTENT_HIDDEN"},
    "merge_cutouts": {"SEMANTIC_CARRIER_UNRESOLVED"},
    "remove_cutout": {"SEMANTIC_CARRIER_UNRESOLVED"},
    "equal_score_candidates": {"SEMANTIC_CARRIER_AMBIGUOUS"},
}


def _resolve_shuffled(case: C.Case, rng: random.Random, hints):
    built = build_package([case.spec], namespace="CERT")
    scene = built.package.scenes[0]
    units, assets = list(scene.units), list(built.assets)
    rng.shuffle(units)
    rng.shuffle(assets)
    items = list(hints.items())
    rng.shuffle(items)
    return SemanticCarrierResolver().resolve(
        scene=scene.model_copy(update={"units": tuple(units)}), assets=assets,
        order_hints=dict(items),
    )


def _hints(resolution) -> dict[str, str]:
    return {
        key: row.members[0].cutout_id
        for key, row in resolution.assignments.items()
        if row.members and row.members[0].source == "locatorless_order_hint"
    }


@pytest.mark.parametrize(("family", "seed"), POSITIVE)
def test_positive_case_maps_every_unit_to_its_true_cutouts(family: str, seed: int) -> None:
    case = C.positive(family, seed)
    outcome = run_story(case)
    assert outcome.error is None, (case.label, outcome.code, str(outcome.error))
    assert mismatches(case, outcome) == [], case.label

    planner, resolution = outcome.planner, outcome.resolution
    # Required semantics never vanish silently; nothing significant is hidden.
    assert {row["status"] for row in planner.semantic_carrier_audit} <= {"CARRIED", "MERGED_VISIBLE"}
    assert planner.hidden_content_audit == []
    # Owned cutouts have exactly one owner; shared carriers carry an explicit reason.
    owned = [m.cutout_id for row in resolution.assignments.values() for m in row.members]
    assert len(owned) == len(set(owned))
    assert all(row.reason for row in resolution.assignments.values() if row.shared)
    # No required intent is left ambiguous or upgraded from ambiguity.
    assert all(
        row.confidence not in {CarrierConfidence.AMBIGUOUS, CarrierConfidence.UNRESOLVED}
        for row in resolution.assignments.values() if row.required
    )
    # Input order (units, cutouts, hint insertion) never changes the normalized result.
    shuffled = _resolve_shuffled(case, random.Random(seed), _hints(resolution))
    assert fingerprint(shuffled) == fingerprint(resolution), case.label


@pytest.mark.parametrize(("family", "seed"), RENDER_PLAN)
def test_positive_case_reaches_render_plan(tmp_path: Path, family: str, seed: int) -> None:
    case = C.positive(family, seed)
    outcome, story, motion, plan, path = run_render_plan(case, tmp_path)
    assert path.is_file()
    assert {asset.id for asset in plan.assets} == {asset.id for asset in outcome.built.assets}
    beats = {beat.id: beat for beat in story}
    assert all(cue.end <= beats[cue.beat_id].end + 1 / 30 + 1e-9 for cue in motion)


@pytest.mark.parametrize(("family", "seed"), FAILURES)
def test_defective_case_fails_before_render_with_its_typed_code(family: str, seed: int) -> None:
    case = C.failure(family, seed)
    outcome = run_story(case)
    expected = "SEMANTIC_CARRIER_AMBIGUOUS" if family == "ambiguous_leader" else case.expected_code
    assert outcome.code == expected, (case.label, outcome.code)
    violation = outcome.error.details["violations"][0]
    assert violation["scene_id"] == outcome.built.scene_ids[0]
    if outcome.code != "AUTHORED_CONTENT_HIDDEN":
        report = violation["resolution"]
        # The failure explains itself without a debugger.
        assert set(report) >= {
            "semantic_asset_id", "roles", "locator_present", "candidates", "selected",
            "shared_carrier", "rejected", "confidence", "ownership_conflict", "reason", "kind",
        }
        assert violation["roles"] and violation["reason"] and report["reason"]
        assert report["confidence"] in {"AMBIGUOUS", "UNRESOLVED", "HIGH_CONFIDENCE", "INFERRED"}
        if outcome.code == "SEMANTIC_CARRIER_AMBIGUOUS":
            assert report["confidence"] == "AMBIGUOUS" and report["ownership_conflict"]
            top, second = report["candidates"][:2]
            assert top["score"] - second["score"] < 0.065
    else:
        assert violation["runtime_asset_id"] and violation["reason"] and violation["area_ratio"]


@pytest.mark.parametrize(("mutation", "seed"), MUTATED)
def test_single_mutation_gives_correct_mapping_or_typed_failure(mutation: str, seed: int) -> None:
    case = C.mutate(mutation, seed)
    outcome = run_story(case)
    if mutation in MUTATION_MUST_FAIL:
        assert outcome.code in MUTATION_MUST_FAIL[mutation], (case.label, outcome.code)
        return
    assert outcome.code is None, (case.label, outcome.code, str(outcome.error))
    assert mismatches(case, outcome) == [], case.label  # never a silently wrong owner
    assert outcome.planner.hidden_content_audit == []


def test_every_failure_in_the_suite_is_typed() -> None:
    codes = {run_story(C.failure(family, 0)).code for family in C.FAILURE_FAMILIES}
    codes |= {run_story(C.mutate(m, 0)).code for m in MUTATION_MUST_FAIL}
    assert codes <= TYPED_FAILURES and None not in codes


@pytest.mark.parametrize("index", range(len(REPRODUCIBILITY)))
def test_repeated_resolution_is_bit_identical(index: int) -> None:
    name, seed = REPRODUCIBILITY[index]
    case = C.mutate(name, seed) if name in C.MUTATIONS else C.positive(name, seed)
    built = build_package([case.spec], namespace="CERT")
    prints = {
        fingerprint(SemanticCarrierResolver().resolve(
            scene=built.package.scenes[0], assets=list(built.assets),
        ))
        for _ in range(REPRODUCIBILITY_RUNS)
    }
    assert len(prints) == 1, case.label


@pytest.mark.parametrize(("family", "seed"), POSITIVE[::6])
def test_far_decorative_cutout_and_optional_context_change_nothing(family: str, seed: int) -> None:
    case = C.positive(family, seed)

    def owners(spec):
        built = build_package([spec], namespace="CERT")
        result = SemanticCarrierResolver().resolve(scene=built.package.scenes[0], assets=built.assets)
        return {key: [m.cutout_id for m in row.members] for key, row in result.assignments.items()}

    base = owners(case.spec)
    # A spot that is genuinely unrelated: outside every cutout and every locator.
    taken = [c.box for c in case.spec.cutouts] + [
        (int((u.locator[0] - u.locator[2] / 2) * 1000), int((u.locator[1] - u.locator[3] / 2) * 1000),
         int(u.locator[2] * 1000), int(u.locator[3] * 1000))
        for u in case.spec.units if u.locator is not None
    ]
    spot = next(
        (x, y) for x, y in ((988, 2), (2, 2), (2, 988), (988, 988), (494, 2), (494, 988), (2, 494))
        if not any(bx - 12 <= x <= bx + bw + 12 and by - 12 <= y <= by + bh + 12
                   for bx, by, bw, bh in taken)
    )
    with_cutout = owners(dataclasses.replace(
        case.spec, cutouts=(*case.spec.cutouts, Cutout("asset-99", (*spot, 9, 9), role="decorative")),
    ))
    assert with_cutout == base
    locator = ((spot[0] + 5) / 1000, (spot[1] + 5) / 1000, 0.01, 0.01)
    with_context = owners(dataclasses.replace(
        case.spec, units=(*case.spec.units, Unit("ZZCONTEXT", (0, 0), locator=locator)),
    ))
    assert {key: value for key, value in with_context.items() if key in base} == base
