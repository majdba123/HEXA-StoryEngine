"""Package-shaped generative certification of semantic-carrier and hidden-art invariants.

Deterministic seeds build Unified-2.0-shaped packages (1-4 scenes) from twelve
production shape families: single / few / many units, decorative-labelled leaders,
compound units split into many cutouts, dotted-line specks, approximate and absent
locators, boundary and overlapping cutouts, results at the scene tail and long
narration windows. Negative seeds insert one defective scene (unresolved carrier,
wrong binding, hidden artwork) and must fail before render with the typed code.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

from app.choreography import ChoreographyDirector
from app.composition import CompositionPlanner
from app.motion import MotionPlanner
from app.render import RenderPlanner
from app.shared.errors import StageFailedError
from app.story import StoryPlanner
from app.text import TextPlanner
from tests.support.carrier_matrix import (
    NEGATIVE_FAMILIES,
    POSITIVE_FAMILIES,
    generate_case,
)
from tests.support.carrier_scene import build_package

POSITIVE_SEEDS = tuple(range(9000, 9240))
DOWNSTREAM_SEEDS = POSITIVE_SEEDS[::2]
NEGATIVE_SEEDS = tuple(range(9500, 9560))
FPS = 30


def test_generated_matrix_covers_every_shape_family() -> None:
    positive = Counter(
        family for seed in POSITIVE_SEEDS for family in generate_case(seed).families
    )
    negative = Counter(
        family
        for seed in NEGATIVE_SEEDS
        for family in generate_case(seed, negative=True).families
        if family in NEGATIVE_FAMILIES
    )
    assert set(positive) == set(POSITIVE_FAMILIES)
    assert min(positive.values()) >= 20
    assert set(negative) == set(NEGATIVE_FAMILIES)
    assert min(negative.values()) >= 10


@pytest.mark.parametrize("seed", POSITIVE_SEEDS)
def test_package_shape_keeps_every_required_carrier_visible(seed: int) -> None:
    case = generate_case(seed)
    built = build_package(list(case.scenes), namespace=f"M{seed}")
    planner = StoryPlanner()
    beats = planner.plan(built.package, built.transcript, built.assets)

    visible = {
        scene_id: {
            asset_id
            for beat in beats if beat.scene_id == scene_id
            for asset_id in (beat.active_visual_semantic_state or {})
        }
        for scene_id in built.scene_ids
    }
    units = {unit.asset_id: unit for scene in built.package.scenes for unit in scene.units}
    for record in planner.semantic_carrier_audit:
        located = units[record["semantic_asset_id"]].visual_locator is not None
        assert record["status"] == "CARRIED" or (
            record["status"] == "MERGED_VISIBLE" and not located
        ), (case.label, record)
        if record["status"] == "CARRIED":
            assert set(record["carrier_asset_ids"]) & visible[record["scene_id"]]
    assert planner.hidden_content_audit == []


@pytest.mark.parametrize("seed", DOWNSTREAM_SEEDS)
def test_package_shape_crosses_every_planning_layer(tmp_path: Path, seed: int) -> None:
    case = generate_case(seed)
    built = build_package(
        list(case.scenes), namespace=f"M{seed}", image_root=tmp_path / "images",
        write_images=True,
    )
    story = StoryPlanner().plan(built.package, built.transcript, built.assets)
    choreography = ChoreographyDirector().plan(built.package, story, built.assets)
    composition = CompositionPlanner().plan(story, built.assets, choreography)
    motion = MotionPlanner().plan(story, composition, choreography, built.assets)
    text = TextPlanner().plan(
        transcript=built.transcript, story=story, assets=built.assets,
        package=built.package, choreography=choreography,
    )
    workspace = tmp_path / "render"
    workspace.mkdir()
    plan, path = RenderPlanner().compile(
        built.transcript, built.assets, story, composition, motion, workspace, text=text,
    )

    assert path.is_file()
    assert {asset.id for asset in plan.assets} == {asset.id for asset in built.assets}
    beats = {beat.id: beat for beat in story}
    for cue in motion:
        beat = beats[cue.beat_id]
        # Timing budget: segmentation-generated cues never run past their scene beat.
        assert cue.end <= beat.end + 1.0 / FPS + 1e-9, (case.label, cue.asset_id)
        leader = any(
            "LEADER" in (row.semantic_event_roles or [])
            for row in beat.asset_activations if row.asset_id == cue.asset_id
        )
        mode = (cue.params.get("semantic_continuity") or {}).get("mode")
        assert not (leader and mode == "NOT_VISIBLE"), (case.label, cue.asset_id)


@pytest.mark.parametrize("seed", NEGATIVE_SEEDS)
def test_defective_package_shape_fails_before_render(seed: int) -> None:
    case = generate_case(seed, negative=True)
    built = build_package(list(case.scenes), namespace=f"N{seed}")
    with pytest.raises(StageFailedError) as caught:
        StoryPlanner().plan(built.package, built.transcript, built.assets)
    assert caught.value.effective_code == case.expected_code, case.label
    violation = caught.value.details["violations"][0]
    assert violation["scene_id"] in built.scene_ids
    assert violation["reason"]
