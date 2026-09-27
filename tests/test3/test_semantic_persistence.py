from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest
from PIL import Image

from app.choreography import ChoreographyDirector
from app.composition import CompositionPlanner
from app.models import (
    AssetActivation,
    PackageModel,
    SceneSource,
    StoryBeat,
    Transcript,
    TranscriptSegment,
    VisualAsset,
)
from app.motion import MotionPlanner
from app.motion.continuity import ContinuityContract
from app.render import RenderPlanner
from app.render.transition import VisualTransitionPolicy


@dataclass(frozen=True)
class Scenario:
    name: str
    beats: tuple[tuple[tuple[str, str], ...], ...]
    durations: tuple[float, ...] = ()
    asset_count: int = 0


SCENARIOS = (
    Scenario("T1_adjacent_persistence", ((('A', 'A'), ('B', 'B')), (('A', 'A'), ('B', 'B'), ('C', 'C')))),
    Scenario("T2_partial_replacement", ((('A', 'A'), ('B', 'B'), ('C', 'C')), (('B', 'B'), ('C', 'C'), ('D', 'D')))),
    Scenario("T3_three_beat_continuity", ((('A', 'A'), ('B', 'B')), (('A', 'A'), ('B', 'B'), ('C', 'C')), (('B', 'B'), ('C', 'C')))),
    Scenario("T4_legitimate_reentry", ((('A', 'A'),), (('B', 'B'),), (('A', 'A'),))),
    Scenario("T5_single_asset", ((('A', 'A'),), (('A', 'A'),), (('A', 'A'),))),
    Scenario("T6_persistent_character", ((('presenter', 'presenter'), ('chart', 'chart')), (('presenter', 'presenter'), ('result', 'result')))),
    Scenario("T7_short_beat", ((('A', 'A'),), (('A', 'A'), ('B', 'B'))), durations=(0.18, 0.18)),
    Scenario("T8_long_beat", ((('A', 'A'),), (('A', 'A'),)), durations=(12.0, 12.0)),
    Scenario("T9_different_semantic_role", ((('A', 'subject'),), (('A', 'result'),))),
    Scenario("T10_comparison_relation", ((('left', 'left'), ('right', 'right')), (('left', 'left'), ('right', 'right')))),
    Scenario("T11_no_character", ((('chart', 'chart'),), (('chart', 'chart'), ('number', 'number')))),
    Scenario("T12_dense_scene", (tuple((f'A{i}', f'A{i}') for i in range(12)), tuple((f'A{i}', f'A{i}') for i in range(4, 16))), asset_count=16),
)


def _build_pipeline(tmp_path: Path, scenario: Scenario):
    asset_ids = sorted({asset_id for beat in scenario.beats for asset_id, _ in beat})
    scene_path = tmp_path / "scene.png"
    Image.new("RGBA", (64, 64), (255, 255, 255, 255)).save(scene_path)
    package = PackageModel(
        root=tmp_path,
        package_id=scenario.name,
        script="continuity fixture",
        scenes=[SceneSource(
            id="scene",
            image_path=scene_path,
            order=0,
            narration_hint="continuity fixture",
            units=[{"unit_id": asset_id, "asset_id": asset_id, "type": "VISUAL_ASSET_INTENT"} for asset_id in asset_ids],
        )],
    )
    assets = [
        VisualAsset(
            id=asset_id,
            scene_id="scene",
            role="object",
            image_path=scene_path,
            source_bbox=(2 + index * 2, 4 + index * 2, 8, 8),
            source_canvas_width=64,
            source_canvas_height=64,
            source_area_ratio=0.02,
            extraction_method="test3-fixture",
        )
        for index, asset_id in enumerate(asset_ids)
    ]
    beats: list[StoryBeat] = []
    cursor = 0.0
    for index, participants in enumerate(scenario.beats):
        duration = scenario.durations[index] if scenario.durations else 1.4
        beats.append(StoryBeat(
            id=f"beat-{index + 1}",
            scene_id="scene",
            start=cursor,
            end=cursor + duration,
            audio_start=cursor,
            audio_end=cursor + duration,
            narration=f"beat {index + 1}",
            primary_asset_ids=[participants[0][0]],
            support_asset_ids=[asset_id for asset_id, _ in participants[1:]],
            action="COMPARE" if scenario.name == "T10_comparison_relation" else "EXPLAIN",
            asset_activations=[
                AssetActivation(
                    asset_id=asset_id,
                    semantic_unit_id=unit_id,
                    spoken_start=cursor,
                    spoken_end=cursor + duration,
                    confidence=1.0,
                    source="final_package_semantic_binding",
                    policy="EXPLICIT",
                )
                for asset_id, unit_id in participants
            ],
        ))
        cursor += duration

    choreography = ChoreographyDirector().plan(package, beats, assets)
    composition = CompositionPlanner().plan(beats, assets, choreography)
    motion = MotionPlanner().plan(beats, composition, choreography, assets)
    transcript = Transcript(
        duration=cursor,
        segments=[TranscriptSegment(start=0.0, end=cursor, text="continuity fixture")],
    )
    render_dir = tmp_path / "render"
    render_dir.mkdir()
    render_plan, _ = RenderPlanner().compile(
        transcript, assets, beats, composition, motion, render_dir
    )
    return beats, choreography, composition, motion, render_plan


def _identities(beat: StoryBeat) -> dict[str, str]:
    return {
        row.asset_id: str(row.semantic_unit_id or row.asset_id)
        for row in beat.asset_activations
    }


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda row: row.name)
def test_sprint1_semantic_persistence_across_planning_pipeline(
    tmp_path: Path, scenario: Scenario
) -> None:
    story, choreography, composition, motion, render_plan = _build_pipeline(tmp_path, scenario)
    assert len(choreography.directives) == len(story)
    assert render_plan.story == story
    assert render_plan.composition == composition
    assert render_plan.motion == motion

    layouts = {row.beat_id: row for row in composition}
    cues = {(row.beat_id, row.asset_id): row for row in motion}
    transition = VisualTransitionPolicy()
    contract = ContinuityContract()

    for previous, current in zip(story, story[1:]):
        previous_identity = _identities(previous)
        current_identity = _identities(current)
        expected = {
            asset_id
            for asset_id, unit_id in previous_identity.items()
            if current_identity.get(asset_id) == unit_id
        }
        previous_layout = layouts[previous.id]
        current_layout = layouts[current.id]
        persistent = contract.persistent_asset_ids(
            previous, current, previous_layout, current_layout
        )
        assert persistent == expected
        assert transition.decide(
            previous,
            previous_layout,
            current_layout,
            current_beat=current,
        ).persistent_asset_ids == expected

        for asset_id in expected:
            previous_cue = cues[(previous.id, asset_id)]
            assert not contract.has_terminal_exit(previous_cue)
            assert cues[(current.id, asset_id)].params["semantic_continuity"]["mode"] == "PERSIST"
        for asset_id in set(current_identity) - expected:
            assert cues[(current.id, asset_id)].params["semantic_continuity"]["mode"] == "ENTER"

    if scenario.name == "T4_legitimate_reentry":
        assert cues[("beat-3", "A")].params["semantic_continuity"]["mode"] == "ENTER"
    if scenario.name == "T9_different_semantic_role":
        assert "A" not in contract.persistent_asset_ids(
            story[0], story[1], layouts["beat-1"], layouts["beat-2"]
        )
    if scenario.name == "T10_comparison_relation":
        assert {"left", "right"}.issubset({row.asset_id for row in layouts["beat-2"].items})
    if scenario.name == "T12_dense_scene":
        assert len(render_plan.assets) == scenario.asset_count
