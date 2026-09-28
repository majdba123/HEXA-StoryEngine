from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest
from PIL import Image

from app.canonical import (
    CanonicalAsset,
    CanonicalPackage,
    CanonicalScene,
    CanonicalScriptSpan,
    CanonicalSemanticEvent,
    CanonicalVisualProgression,
)
from app.choreography import ChoreographyDirector
from app.composition import CompositionPlanner
from app.models import (
    AssetActivation,
    CompositionBeat,
    LayoutItem,
    PackageModel,
    SceneSource,
    StoryBeat,
    Transcript,
    TranscriptSegment,
    TranscriptWord,
    VisualAsset,
)
from app.motion import MotionPlanner
from app.motion.continuity import ContinuityContract
from app.render import RenderPlanner
from app.render.renderer import FFmpegRenderer
from app.render.transition import VisualTransitionPolicy
from app.story import StoryPlanner
from app.story.windows import StoryAssetActivation


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


def _real_story_pipeline(tmp_path: Path):
    script = "alpha beta gamma delta"
    image_path = tmp_path / "semantic-state.png"
    Image.new("RGBA", (64, 64), (255, 255, 255, 255)).save(image_path)
    spans = {
        "A": (0, 5, "alpha", "E1", ()),
        "B": (6, 10, "beta", "E1", ()),
        "C": (11, 16, "gamma", "E2", ("E1",)),
        "D": (17, 22, "delta", "E3", ("E2",)),
    }
    units = tuple(
        CanonicalAsset(
            unit_id=asset_id,
            asset_id=asset_id,
            scene_id="scene",
            script_text=text,
            script_span=CanonicalScriptSpan(
                text=text, global_char_start=start, global_char_end=end
            ),
            binding_type="EXPLICIT",
            semantic_event_id=event_id,
        )
        for asset_id, (start, end, text, event_id, _dependencies) in spans.items()
    )
    events = tuple(
        CanonicalSemanticEvent(
            semantic_event_id=event_id,
            scene_id="scene",
            script_text=text,
            script_span=CanonicalScriptSpan(
                text=text, global_char_start=start, global_char_end=end
            ),
            sequence_order=index,
            visual_leader_asset_id=asset_id,
            participant_asset_ids=("B",) if event_id == "E1" else (),
            depends_on_event_ids=dependencies,
        )
        for index, (asset_id, (start, end, text, event_id, dependencies))
        in enumerate((row for row in spans.items() if row[0] != "B"), start=1)
    )
    progression_rows = (
        ("A", 0, 10, "alpha beta"),
        ("C", 11, 16, "gamma"),
        ("D", 17, 22, "delta"),
    )
    progressions = tuple(
        CanonicalVisualProgression(
            action="EXPLAIN",
            targets=(asset_id,),
            trigger=CanonicalScriptSpan(
                text=text, global_char_start=start, global_char_end=end
            ),
        )
        for asset_id, start, end, text in progression_rows
    )
    package = CanonicalPackage(
        root=tmp_path,
        package_id="semantic-state",
        script=script,
        semantic_binding_schema_name="HEXA_ASSET_LEVEL_SEMANTIC_BINDINGS",
        semantic_bindings_present=True,
        scenes=(CanonicalScene(
            id="scene",
            image_path=image_path,
            order=0,
            script_char_start=0,
            script_char_end=len(script),
            units=units,
            visual_progression=progressions,
            semantic_events=events,
        ),),
    )
    transcript = Transcript(
        duration=3.0,
        segments=[],
        timing_source="forced_alignment",
        words=[
            TranscriptWord(start=0.10, end=0.35, text="alpha", char_start=0, char_end=5),
            TranscriptWord(start=0.40, end=0.65, text="beta", char_start=6, char_end=10),
            TranscriptWord(start=1.10, end=1.35, text="gamma", char_start=11, char_end=16),
            TranscriptWord(start=2.10, end=2.35, text="delta", char_start=17, char_end=22),
        ],
    )
    assets = [
        VisualAsset(
            id=asset_id,
            scene_id="scene",
            role="object",
            image_path=image_path,
            extraction_method="test3-real-story-fixture",
            source_area_ratio=0.20 - index * 0.01,
        )
        for index, asset_id in enumerate(spans)
    ]
    story = StoryPlanner().plan(package, transcript, assets)
    choreography = ChoreographyDirector().plan(package, story, assets)
    composition = CompositionPlanner().plan(story, assets, choreography)
    motion = MotionPlanner().plan(story, composition, choreography, assets)
    render_dir = tmp_path / "real-render-plan"
    render_dir.mkdir()
    render_plan, _ = RenderPlanner().compile(
        transcript, assets, story, composition, motion, render_dir
    )
    return story, choreography, composition, motion, render_plan


def test_story_planner_builds_dependency_closed_active_visual_state(tmp_path: Path) -> None:
    story, choreography, composition, motion, render_plan = _real_story_pipeline(tmp_path)

    assert [beat.active_visual_semantic_state for beat in story] == [
        {"A": "A", "B": "B"},
        {"A": "A", "B": "B", "C": "C"},
        {"A": "A", "B": "B", "C": "C", "D": "D"},
    ]
    assert len(choreography.directives) == 3
    assert render_plan.story == story
    assert render_plan.composition == composition
    assert render_plan.motion == motion

    cues = {(cue.beat_id, cue.asset_id): cue for cue in motion}
    for beat_id, asset_ids in (("beat-002", {"A", "B"}), ("beat-003", {"A", "B", "C"})):
        for asset_id in asset_ids:
            cue = cues[(beat_id, asset_id)]
            assert cue.params["semantic_continuity"]["mode"] == "PERSIST"
            assert not ContinuityContract.has_terminal_exit(cue)


def test_renderer_visibility_has_no_gap_for_dependency_persistence(tmp_path: Path) -> None:
    story, _choreography, _composition, motion, _render_plan = _real_story_pipeline(tmp_path)
    cue = next(row for row in motion if row.beat_id == "beat-002" and row.asset_id == "A")
    beat = story[1]
    duration = beat.end - beat.start
    reveal_start, _end, _fade = FFmpegRenderer._cue_window(
        beat=beat, cue=cue, segment_start=beat.start, duration=duration
    )
    assert FFmpegRenderer.asset_visibility_window(
        cue=cue,
        segment_start=beat.start,
        duration=duration,
        reveal_start=reveal_start,
        persistent=True,
    ) == pytest.approx((0.0, duration))


def test_safe_abstention_never_enters_active_visual_state() -> None:
    abstention = StoryAssetActivation(
        asset_id="A",
        semantic_unit_id="A",
        semantic_event_id="E1",
        activation_policy="SAFE_ABSTENTION",
    )
    dependent = StoryAssetActivation(
        asset_id="B",
        semantic_unit_id="B",
        semantic_event_id="E2",
        semantic_event_dependency_ids=["E1"],
        phrase_start=1.0,
        phrase_end=1.5,
        reveal_start=1.0,
        semantic_peak=1.2,
        settle_at=1.4,
        activation_policy="OWN_WINDOW",
    )
    beats = StoryPlanner._resolve_active_visual_semantic_state([
        StoryBeat(id="one", scene_id="scene", start=0, end=1, narration="one", action="EXPLAIN", asset_activations=[abstention]),
        StoryBeat(id="two", scene_id="scene", start=1, end=2, narration="two", action="EXPLAIN", asset_activations=[dependent]),
    ])
    assert beats[0].active_visual_semantic_state == {}
    assert beats[1].active_visual_semantic_state == {"B": "B"}


def test_active_state_retires_assets_and_resets_at_scene_boundary() -> None:
    first = StoryBeat(
        id="one",
        scene_id="scene-one",
        start=0,
        end=1,
        narration="one",
        action="EXPLAIN",
        active_visual_semantic_state={"A": "A", "B": "B", "C": "C"},
    )
    retired = first.model_copy(update={
        "id": "two",
        "start": 1,
        "end": 2,
        "active_visual_semantic_state": {"B": "B", "C": "C"},
    })
    next_scene = retired.model_copy(update={
        "id": "three",
        "scene_id": "scene-two",
        "start": 2,
        "end": 3,
    })
    layouts = [
        CompositionBeat(
            beat_id=beat.id,
            items=[
                LayoutItem(
                    asset_id=asset_id, x=0.5, y=0.5, width=0.2, height=0.2
                )
                for asset_id in ("A", "B", "C")
            ],
        )
        for beat in (first, retired, next_scene)
    ]
    contract = ContinuityContract()
    assert contract.persistent_asset_ids(first, retired, layouts[0], layouts[1]) == {"B", "C"}
    assert contract.persistent_asset_ids(retired, next_scene, layouts[1], layouts[2]) == set()


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
