from __future__ import annotations

from app.choreography import ChoreographyDirector
from app.composition import CompositionPlanner
from app.shared.handoff import LayerHandoffValidator
from app.final_package import FinalPackageLoader
from app.motion import MotionPlanner
from app.render import RenderPlanner
from app.story import StoryPlanner
from app.text import TextPlanner
from tests.test1.factory import (
    DiskPackageShape,
    controlled_visual_assets,
    deterministic_transcript,
    write_valid_package,
)


def _run_with_shared_services(
    tmp_path, namespace: str, services, shape: DiskPackageShape | None = None
):
    story_planner, choreography_director, composition_planner, motion_planner, text_planner, render_planner = services
    shape = shape or DiskPackageShape(
        scenes=2,
        assets_per_scene=4,
        relations=True,
        dependency_mode="branching",
        locators="partial",
        reuse_first_asset=True,
        namespace=namespace,
    )
    if shape.namespace != namespace:
        shape = DiskPackageShape(
            scenes=shape.scenes,
            assets_per_scene=shape.assets_per_scene,
            relations=shape.relations,
            dependencies=shape.dependencies,
            dependency_mode=shape.dependency_mode,
            locators=shape.locators,
            extra_metadata=shape.extra_metadata,
            compound=shape.compound,
            progression=shape.progression,
            group_count=shape.group_count,
            group_policy=shape.group_policy,
            binding_types=shape.binding_types,
            continuity=shape.continuity,
            reuse_first_asset=shape.reuse_first_asset,
            script_style=shape.script_style,
            namespace=namespace,
        )
    source = write_valid_package(tmp_path / namespace / "source", shape)
    raw = FinalPackageLoader().load(source, tmp_path / namespace / "work")
    canonical = raw
    transcript = deterministic_transcript(canonical)
    assets = controlled_visual_assets(canonical)
    contracts = LayerHandoffValidator()
    contracts.require_assets_for_story(package=canonical, assets=assets)
    story = story_planner.plan(canonical, transcript, assets)
    contracts.require_story_for_choreography(
        package=canonical, transcript=transcript, assets=assets, story=story
    )
    choreography = choreography_director.plan(canonical, story, assets)
    contracts.require_choreography_for_composition(
        story=story, assets=assets, choreography=choreography
    )
    composition = composition_planner.plan(story, assets, choreography)
    contracts.require_composition_for_motion(
        story=story, assets=assets, composition=composition
    )
    motion = motion_planner.plan(story, composition, choreography, assets)
    contracts.require_motion_for_text_and_render(
        story=story, assets=assets, composition=composition,
        choreography=choreography, motion=motion,
    )
    text = text_planner.plan(
        transcript=transcript,
        story=story,
        assets=assets,
        package=canonical,
        choreography=choreography,
    )
    contracts.require_text_for_composition(
        transcript=transcript, story=story, assets=assets, text=text
    )
    workspace = tmp_path / namespace / "render"
    workspace.mkdir(parents=True, exist_ok=True)
    plan, _ = render_planner.compile(
        transcript, assets, story, composition, motion, workspace, text=text
    )
    return canonical, story, choreography, composition, motion, text, plan


def _assert_current_namespace(namespace: str, result) -> None:
    canonical, story, choreography, composition, motion, text, plan = result
    asset_ids = set(canonical.asset_by_id)
    event_ids = set(canonical.event_by_id)
    beat_ids = {beat.id for beat in story}

    assert asset_ids and all(asset_id.startswith(f"{namespace}_") for asset_id in asset_ids)
    assert all(beat.scene_id.startswith(f"{namespace}_") for beat in story)
    assert all(
        activation.asset_id in asset_ids
        and (
            activation.semantic_event_id is None
            or activation.semantic_event_id in event_ids
        )
        for beat in story
        for activation in beat.asset_activations
    )
    assert all(item.asset_id in asset_ids for beat in composition for item in beat.items)
    assert all(cue.asset_id in asset_ids and cue.beat_id in beat_ids for cue in motion)
    assert all(cue.beat_id in beat_ids for cue in text.cues)
    assert {asset.id for asset in plan.assets} == asset_ids

    for directive in choreography.directives:
        for candidate in (
            directive.primary_asset_id,
            directive.interaction_asset_id,
        ):
            if candidate:
                assert candidate in asset_ids


def test_sequential_packages_do_not_leak_state_between_runs(tmp_path) -> None:
    services = (
        StoryPlanner(),
        ChoreographyDirector(),
        CompositionPlanner(),
        MotionPlanner(),
        TextPlanner(),
        RenderPlanner(),
    )

    for run_index, namespace in enumerate(("PKGA", "PKGB", "PKGC", "PKGD", "PKGA")):
        result = _run_with_shared_services(
            tmp_path / f"run-{run_index}", namespace, services
        )
        _assert_current_namespace(namespace, result)


def _planning_signature(result):
    _, story, choreography, composition, motion, text, _ = result
    return story, choreography, composition, motion, text


def test_varied_package_shapes_do_not_contaminate_following_runs(tmp_path) -> None:
    services = (
        StoryPlanner(),
        ChoreographyDirector(),
        CompositionPlanner(),
        MotionPlanner(),
        TextPlanner(),
        RenderPlanner(),
    )
    shapes = (
        DiskPackageShape(scenes=1, assets_per_scene=1, namespace="ISO1"),
        DiskPackageShape(scenes=2, assets_per_scene=5, dependency_mode="linear", locators="all", namespace="ISO2"),
        DiskPackageShape(scenes=3, assets_per_scene=4, dependency_mode="branching", locators="partial", reuse_first_asset=True, namespace="ISO3"),
        DiskPackageShape(scenes=1, assets_per_scene=20, group_count=4, script_style="arabic", namespace="ISO4"),
        DiskPackageShape(scenes=2, assets_per_scene=6, compound=True, dependency_mode="branching", namespace="ISO5"),
        DiskPackageShape(scenes=2, assets_per_scene=4, continuity="persist", script_style="numbers", namespace="ISO6"),
        DiskPackageShape(scenes=2, assets_per_scene=4, continuity="transform", locators="all", namespace="ISO7"),
        DiskPackageShape(scenes=2, assets_per_scene=7, progression=False, relations=False, dependencies=False, namespace="ISO8"),
        DiskPackageShape(scenes=3, assets_per_scene=3, group_count=3, group_policy="SIMULTANEOUS_VISUAL_UNIT", namespace="ISO9"),
        DiskPackageShape(scenes=2, assets_per_scene=8, binding_types=("EXPLICIT", "SEMANTIC", "PARENT"), namespace="ISO10"),
    )

    for run_index, shape in enumerate(shapes):
        result = _run_with_shared_services(
            tmp_path / f"varied-{run_index}", shape.namespace, services, shape
        )
        _assert_current_namespace(shape.namespace, result)


def test_package_output_is_order_independent_with_shared_services(tmp_path) -> None:
    services = (
        StoryPlanner(),
        ChoreographyDirector(),
        CompositionPlanner(),
        MotionPlanner(),
        TextPlanner(),
        RenderPlanner(),
    )
    target = DiskPackageShape(
        scenes=2,
        assets_per_scene=6,
        dependency_mode="branching",
        locators="partial",
        compound=True,
        reuse_first_asset=True,
        script_style="arabic",
        namespace="STABLE",
    )
    disruptor = DiskPackageShape(
        scenes=3,
        assets_per_scene=9,
        dependency_mode="linear",
        locators="all",
        group_count=3,
        continuity="persist",
        script_style="numbers",
        namespace="NOISE",
    )

    first = _run_with_shared_services(tmp_path / "first", "STABLE", services, target)
    _run_with_shared_services(tmp_path / "middle", "NOISE", services, disruptor)
    second = _run_with_shared_services(tmp_path / "second", "STABLE", services, target)

    assert _planning_signature(first) == _planning_signature(second)
