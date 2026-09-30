"""Growth stress for future Final Packages: 50/100 scenes, dense fragments, tight beats.

Measured on the development machine: 50 scenes (~230 cutouts, ~125 events) plan
end-to-end in ~10 s and 100 scenes (~470 cutouts, ~240 events) in ~16 s at <100 MB
Python heap. Budgets below are ~4x headroom so CI catches super-linear regressions
without flaking.
"""

from __future__ import annotations

import time
import tracemalloc
from pathlib import Path

import pytest

from app.choreography import ChoreographyDirector
from app.composition import CompositionPlanner
from app.motion import MotionPlanner
from app.render import RenderPlanner
from app.story import StoryPlanner
from app.text import TextPlanner
from tests.support.carrier_matrix import POSITIVE_FAMILIES, family_case
from tests.support.carrier_scene import build_package


def _full_plan(tmp_path: Path, scenes, namespace: str):
    built = build_package(
        scenes, namespace=namespace, image_root=tmp_path / "images", write_images=True,
    )
    planner = StoryPlanner()
    story = planner.plan(built.package, built.transcript, built.assets)
    choreography = ChoreographyDirector().plan(built.package, story, built.assets)
    composition = CompositionPlanner().plan(story, built.assets, choreography)
    motion = MotionPlanner().plan(story, composition, choreography, built.assets)
    text = TextPlanner().plan(
        transcript=built.transcript, story=story, assets=built.assets,
        package=built.package, choreography=choreography,
    )
    workspace = tmp_path / "render"
    workspace.mkdir()
    plan, _ = RenderPlanner().compile(
        built.transcript, built.assets, story, composition, motion, workspace, text=text,
    )
    return built, planner, story, motion, plan


def _assert_contracts(built, planner, story, motion, plan) -> None:
    assert len(story) == len(built.package.scenes)
    assert {asset.id for asset in plan.assets} == {asset.id for asset in built.assets}
    assert planner.hidden_content_audit == []
    assert {row["status"] for row in planner.semantic_carrier_audit} <= {
        "CARRIED", "MERGED_VISIBLE",
    }
    beats = {beat.id: beat for beat in story}
    assert all(cue.end <= beats[cue.beat_id].end + 1 / 30 + 1e-9 for cue in motion)


@pytest.mark.parametrize(("scene_count", "budget_s", "heap_mb"), [(50, 45.0, 200), (100, 75.0, 400)])
def test_large_package_plans_within_budget(
    tmp_path: Path, scene_count: int, budget_s: float, heap_mb: int,
) -> None:
    scenes = [
        family_case(POSITIVE_FAMILIES[index % len(POSITIVE_FAMILIES)], 5000 + index).scenes[0]
        for index in range(scene_count)
    ]
    tracemalloc.start()
    started = time.perf_counter()
    try:
        result = _full_plan(tmp_path, scenes, f"STRESS{scene_count}")
        elapsed = time.perf_counter() - started
        peak = tracemalloc.get_traced_memory()[1] / 1e6
    finally:
        tracemalloc.stop()
    _assert_contracts(*result)
    assert elapsed < budget_s, f"{scene_count} scenes planned in {elapsed:.1f}s"
    assert peak < heap_mb, f"{scene_count} scenes peaked at {peak:.0f} MB"


def test_fragment_heavy_short_scenes_respect_every_beat_budget(tmp_path: Path) -> None:
    """Over-segmented units and dotted specks on adjacent short scenes."""
    scenes = [
        family_case("compound_split" if index % 2 else "dotted", 6000 + index).scenes[0]
        for index in range(30)
    ]
    built, planner, story, motion, plan = _full_plan(tmp_path, scenes, "FRAG")
    _assert_contracts(built, planner, story, motion, plan)
    assert sum(len(scene.cutouts) for scene in scenes) >= 150
