from __future__ import annotations

from math import isfinite

import pytest

from app.canonical import CanonicalNormalizer
from app.choreography import ChoreographyDirector
from app.composition import CompositionPlanner
from app.final_package import FinalPackageLoader
from app.motion import MotionPlanner
from app.render import RenderPlanner
from app.story import StoryPlanner
from app.text import TextPlanner
from tests.test1.factory import (
    DiskPackageShape,
    controlled_visual_assets,
    deterministic_transcript,
    seeded_disk_shape,
    write_valid_package,
)


def _plan(tmp_path, shape: DiskPackageShape):
    source = write_valid_package(tmp_path / "source", shape)
    raw = FinalPackageLoader().load(source, tmp_path / "work")
    canonical = CanonicalNormalizer().normalize(raw)
    transcript = deterministic_transcript(canonical)
    assets = controlled_visual_assets(canonical)
    story = StoryPlanner().plan(canonical, transcript, assets)
    choreography = ChoreographyDirector().plan(canonical, story, assets)
    composition = CompositionPlanner().plan(story, assets, choreography)
    motion = MotionPlanner().plan(story, composition, choreography, assets)
    text = TextPlanner().plan(
        transcript=transcript,
        story=story,
        assets=assets,
        package=canonical,
        choreography=choreography,
    )
    render_workspace = tmp_path / "render"
    render_workspace.mkdir(parents=True, exist_ok=True)
    render_plan, _ = RenderPlanner().compile(
        transcript,
        assets,
        story,
        composition,
        motion,
        render_workspace,
        text=text,
    )
    return canonical, story, choreography, composition, motion, text, render_plan


def test_generated_package_reaches_render_plan_with_resolved_references(tmp_path) -> None:
    canonical, story, choreography, composition, motion, text, plan = _plan(
        tmp_path,
        DiskPackageShape(scenes=2, assets_per_scene=4, relations=True, dependencies=True),
    )
    asset_ids = set(canonical.asset_by_id)
    beat_ids = {beat.id for beat in story}

    assert story
    assert choreography.directives
    assert composition
    assert motion
    assert plan.duration > 0
    assert {asset.id for asset in plan.assets} == asset_ids
    assert all(item.asset_id in asset_ids for beat in composition for item in beat.items)
    assert all(cue.asset_id in asset_ids and cue.beat_id in beat_ids for cue in motion)
    assert all(isfinite(cue.start) and isfinite(cue.end) and cue.end >= cue.start for cue in motion)
    assert all(cue.beat_id in beat_ids for cue in text.cues)
    assert {beat.id for beat in plan.story} == beat_ids


FULL_LAYER_SEEDS = tuple(range(4101, 4201))


@pytest.mark.parametrize("seed", FULL_LAYER_SEEDS)
def test_seeded_valid_packages_reach_render_plan_without_foreign_references(
    tmp_path, seed: int
) -> None:
    canonical, story, choreography, composition, motion, text, plan = _plan(
        tmp_path, seeded_disk_shape(seed)
    )
    asset_ids = set(canonical.asset_by_id)
    event_ids = set(canonical.event_by_id)
    beat_ids = {beat.id for beat in story}

    assert plan.story == story
    assert {asset.id for asset in plan.assets} == asset_ids
    assert all(activation.asset_id in asset_ids for beat in story for activation in beat.asset_activations)
    assert all(
        not activation.semantic_event_id or activation.semantic_event_id in event_ids
        for beat in story for activation in beat.asset_activations
    )
    assert all(item.asset_id in asset_ids for beat in composition for item in beat.items)
    assert all(cue.asset_id in asset_ids and cue.beat_id in beat_ids for cue in motion)
    assert all(isfinite(cue.start) and isfinite(cue.end) and cue.end >= cue.start for cue in motion)
    assert all(cue.beat_id in beat_ids for cue in text.cues)


@pytest.mark.parametrize(
    "shape",
    [
        DiskPackageShape(scenes=1, assets_per_scene=1, relations=False, dependencies=False),
        DiskPackageShape(scenes=1, assets_per_scene=20, locators="partial", group_count=2),
        DiskPackageShape(scenes=8, assets_per_scene=6, dependency_mode="branching", reuse_first_asset=True),
        DiskPackageShape(scenes=4, assets_per_scene=5, progression=False, locators="none"),
        DiskPackageShape(scenes=3, assets_per_scene=6, group_count=2, group_policy="SIMULTANEOUS_VISUAL_UNIT"),
        DiskPackageShape(scenes=3, assets_per_scene=5, compound=True, script_style="arabic"),
        DiskPackageShape(scenes=3, assets_per_scene=5, script_style="numbers", continuity="persist"),
        DiskPackageShape(scenes=3, assets_per_scene=5, continuity="transform"),
        DiskPackageShape(scenes=2, assets_per_scene=5, binding_types=("EXPLICIT", "SUPPORT")),
        DiskPackageShape(scenes=2, assets_per_scene=5, binding_types=("SEMANTIC", "AMBIGUOUS")),
        DiskPackageShape(scenes=2, assets_per_scene=5, binding_types=("EXPLICIT", "PARENT", "SEMANTIC")),
    ],
    ids=[
        "minimal", "dense-20", "branching-reuse", "no-progression",
        "simultaneous-groups", "arabic-compound", "numbers-persist",
        "transform-continuity", "support-bindings", "ambiguous-bindings",
        "parent-bindings",
    ],
)
def test_fixed_topology_matrix_reaches_render_plan(tmp_path, shape: DiskPackageShape) -> None:
    canonical, story, _choreography, composition, motion, text, plan = _plan(tmp_path, shape)
    asset_ids = set(canonical.asset_by_id)
    beat_ids = {beat.id for beat in story}

    assert canonical.scenes
    assert story
    assert plan.duration > 0
    assert all(item.asset_id in asset_ids for beat in composition for item in beat.items)
    assert all(cue.asset_id in asset_ids and cue.beat_id in beat_ids for cue in motion)
    assert all(cue.beat_id in beat_ids for cue in text.cues)
