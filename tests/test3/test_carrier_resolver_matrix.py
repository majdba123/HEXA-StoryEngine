"""Resolver-focused generative matrix: invariants through Story and RenderPlan.

Deterministic seeds over resolver shape families (repeated icons, jittered locators,
extra Vision components, under-segmentation, one missing locator, dense 25/50-unit
scenes) assert ownership invariants rather than hand-picked mappings; negative
families must fail before render with their typed code. Dense scenes also bound the
resolver's per-scene cost.
"""

from __future__ import annotations

import json
import random
import time
from pathlib import Path

import pytest

from app.choreography import ChoreographyDirector
from app.composition import CompositionPlanner
from app.motion import MotionPlanner
from app.render import RenderPlanner
from app.shared.errors import StageFailedError
from app.story import StoryPlanner
from app.story.carrier_resolver import CarrierConfidence, SemanticCarrierResolver
from app.text import TextPlanner
from tests.support.carrier_matrix import (
    RESOLVER_FAMILIES,
    RESOLVER_NEGATIVE_FAMILIES,
    resolver_case,
)
from tests.support.carrier_scene import Cutout, SceneSpec, Unit, build_package, locator_for

SEEDS_PER_FAMILY = 20
POSITIVE = [(family, 8000 + index) for family in RESOLVER_FAMILIES for index in range(SEEDS_PER_FAMILY)]
NEGATIVE = [(family, 8500 + index) for family in sorted(RESOLVER_NEGATIVE_FAMILIES) for index in range(15)]
DOWNSTREAM = [row for row in POSITIVE if row[1] % 4 == 0 and row[0] != "dense_50"]


@pytest.mark.parametrize(("family", "seed"), POSITIVE)
def test_resolver_shape_keeps_ownership_invariants_through_story(family: str, seed: int) -> None:
    case = resolver_case(family, seed)
    built = build_package(list(case.scenes), namespace=f"R{seed}")
    planner = StoryPlanner()
    beats = planner.plan(built.package, built.transcript, built.assets)
    scene = built.package.scenes[0]
    resolution = planner.activation.carrier_resolutions[beats[0].id]
    real = {asset.id for asset in built.assets}

    # Output references only authored ids and real cutouts of this scene.
    assert set(resolution.assignments) == {unit.asset_id for unit in scene.assets}
    owned = [m.cutout_id for row in resolution.assignments.values() for m in row.members]
    assert set(owned) <= real and len(owned) == len(set(owned))
    # Required semantics never vanish: a carrier, or a typed failure (none here).
    statuses = {row["status"] for row in planner.semantic_carrier_audit}
    assert statuses <= {"CARRIED", "MERGED_VISIBLE"}, (case.label, statuses)
    assert planner.hidden_content_audit == []
    assert all(
        row.confidence is not CarrierConfidence.AMBIGUOUS
        for row in resolution.assignments.values() if row.required
    )
    if family == "under_segmented":
        shared = {row.shared.cutout_id for row in resolution.assignments.values() if row.shared}
        assert len(shared) == 1 and len(resolution.owners[next(iter(shared))]) == 2
    if family in {"repeated_icons", "jittered_locators", "dense_25", "dense_50"}:
        assert len(owned) == len(scene.assets), "every located intent owns exactly its cutout"

    # Same inputs in any order -> byte-identical resolution.
    rng = random.Random(seed)
    units, assets = list(scene.units), list(built.assets)
    rng.shuffle(units)
    rng.shuffle(assets)
    again = SemanticCarrierResolver().resolve(
        scene=scene.model_copy(update={"units": tuple(units)}), assets=assets,
        order_hints={
            key: row.members[0].cutout_id
            for key, row in resolution.assignments.items()
            if row.members and row.members[0].source == "locatorless_order_hint"
        },
    )
    assert json.dumps(again.to_payload(), sort_keys=True) == json.dumps(
        resolution.to_payload(), sort_keys=True,
    )


@pytest.mark.parametrize(("family", "seed"), DOWNSTREAM)
def test_resolver_shape_reaches_render_plan(tmp_path: Path, family: str, seed: int) -> None:
    case = resolver_case(family, seed)
    built = build_package(
        list(case.scenes), namespace=f"R{seed}", image_root=tmp_path / "images", write_images=True,
    )
    story = StoryPlanner().plan(built.package, built.transcript, built.assets)
    choreography = ChoreographyDirector().plan(built.package, story, built.assets)
    composition = CompositionPlanner().plan(story, built.assets, choreography)
    motion = MotionPlanner().plan(story, composition, choreography, built.assets)
    text = TextPlanner().plan(
        transcript=built.transcript, story=story, assets=built.assets,
        package=built.package, choreography=choreography,
    )
    (tmp_path / "render").mkdir()
    plan, path = RenderPlanner().compile(
        built.transcript, built.assets, story, composition, motion, tmp_path / "render", text=text,
    )
    assert path.is_file()
    assert {asset.id for asset in plan.assets} == {asset.id for asset in built.assets}
    beats = {beat.id: beat for beat in story}
    assert all(cue.end <= beats[cue.beat_id].end + 1 / 30 + 1e-9 for cue in motion)


@pytest.mark.parametrize(("family", "seed"), NEGATIVE)
def test_resolver_defect_fails_before_render_with_typed_code(family: str, seed: int) -> None:
    case = resolver_case(family, seed)
    built = build_package(list(case.scenes), namespace=f"RN{seed}")
    with pytest.raises(StageFailedError) as caught:
        StoryPlanner().plan(built.package, built.transcript, built.assets)
    assert caught.value.effective_code == case.expected_code, case.label
    violation = caught.value.details["violations"][0]
    assert violation["resolution"]["candidates"] is not None
    assert violation["resolution"]["confidence"] in {"AMBIGUOUS", "UNRESOLVED"}


@pytest.mark.parametrize(("count", "budget_ms"), [(1, 50), (5, 50), (10, 80), (25, 250), (50, 900), (100, 4000)])
def test_resolver_cost_stays_bounded_on_dense_scenes(count: int, budget_ms: int) -> None:
    """O(n^2) scoring + O(n^3) assignment per scene; measured ~1 ms at 10, ~0.2 s at 50."""
    columns = max(1, int(count ** 0.5 + 0.999))
    cell = 1000 // columns
    boxes = [((i % columns) * cell + 6, (i // columns) * cell + 6, cell - 12, cell - 12)
             for i in range(count)]
    spec = SceneSpec(
        phrase=tuple(f"w{i}" for i in range(6)),
        units=tuple(Unit(f"U{i:03d}", (0, 0), locator=locator_for(box)) for i, box in enumerate(boxes)),
        cutouts=tuple(Cutout(f"asset-{i + 1:03d}", box) for i, box in enumerate(boxes)),
    )
    built = build_package([spec])
    scene = built.package.scenes[0]
    started = time.perf_counter()
    resolution = SemanticCarrierResolver().resolve(scene=scene, assets=built.assets)
    elapsed_ms = (time.perf_counter() - started) * 1000
    assert sum(len(row.members) for row in resolution.assignments.values()) == count
    assert elapsed_ms < budget_ms, f"{count} intents resolved in {elapsed_ms:.0f} ms"
