from __future__ import annotations

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
    write_valid_package,
)


def _run_with_shared_services(tmp_path, namespace: str, services):
    story_planner, choreography_director, composition_planner, motion_planner, text_planner, render_planner = services
    shape = DiskPackageShape(
        scenes=2,
        assets_per_scene=4,
        relations=True,
        dependency_mode="branching",
        locators="partial",
        reuse_first_asset=True,
        namespace=namespace,
    )
    source = write_valid_package(tmp_path / namespace / "source", shape)
    raw = FinalPackageLoader().load(source, tmp_path / namespace / "work")
    canonical = CanonicalNormalizer().normalize(raw)
    transcript = deterministic_transcript(canonical)
    assets = controlled_visual_assets(canonical)
    story = story_planner.plan(canonical, transcript, assets)
    choreography = choreography_director.plan(canonical, story, assets)
    composition = composition_planner.plan(story, assets, choreography)
    motion = motion_planner.plan(story, composition, choreography, assets)
    text = text_planner.plan(
        transcript=transcript,
        story=story,
        assets=assets,
        package=canonical,
        choreography=choreography,
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
