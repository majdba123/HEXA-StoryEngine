from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import random

import pytest
from PIL import Image

from app.canonical import (
    CanonicalAsset,
    CanonicalPackage,
    CanonicalScene,
    CanonicalScriptSpan,
    CanonicalSemanticEvent,
    CanonicalVisualLocator,
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
from app.motion.lifetime import SemanticVisualLifetimeIndex
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

    beats = StoryPlanner._resolve_active_visual_semantic_state(beats)
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


def test_active_state_cannot_retire_assets_and_resets_at_scene_boundary() -> None:
    first = StoryBeat(
        id="one",
        scene_id="scene-one",
        start=0,
        end=1,
        narration="one",
        action="EXPLAIN",
        active_visual_semantic_state={"A": "A", "B": "B", "C": "C"},
    )
    attempted_retirement = first.model_copy(update={
        "id": "two",
        "start": 1,
        "end": 2,
        "active_visual_semantic_state": {"B": "B", "C": "C"},
    })
    next_scene = attempted_retirement.model_copy(update={
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
        for beat in (first, attempted_retirement, next_scene)
    ]
    contract = ContinuityContract()
    assert contract.persistent_asset_ids(
        first, attempted_retirement, layouts[0], layouts[1]
    ) == {"B", "C"}
    assert contract.persistent_asset_ids(
        attempted_retirement, next_scene, layouts[1], layouts[2]
    ) == set()


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
        expected = set(previous.active_visual_semantic_state or {})
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
        for asset_id in set(current.active_visual_semantic_state or {}) - expected:
            assert cues[(current.id, asset_id)].params["semantic_continuity"]["mode"] == "ENTER"

    if scenario.name == "T4_legitimate_reentry":
        assert cues[("beat-3", "A")].params["semantic_continuity"]["mode"] == "PERSIST"
    if scenario.name == "T9_different_semantic_role":
        assert "A" in contract.persistent_asset_ids(
            story[0], story[1], layouts["beat-1"], layouts["beat-2"]
        )
    if scenario.name == "T10_comparison_relation":
        assert {"left", "right"}.issubset({row.asset_id for row in layouts["beat-2"].items})
    if scenario.name == "T12_dense_scene":
        assert len(render_plan.assets) == scenario.asset_count


def _assert_monotonic_scene_lifecycle(beats: list[StoryBeat]) -> None:
    entered_by_scene: dict[str, set[str]] = {}
    previous_scene: str | None = None
    previous_visible: set[str] = set()
    for beat in beats:
        visible = set(beat.active_visual_semantic_state or {})
        if beat.scene_id != previous_scene:
            previous_visible = set()
        assert previous_visible <= visible
        entered = entered_by_scene.setdefault(beat.scene_id, set())
        newly_visible = visible - previous_visible
        assert not (newly_visible & entered)
        entered.update(newly_visible)
        previous_visible = visible
        previous_scene = beat.scene_id


def test_320_deterministic_generated_scene_lifecycles_are_monotonic() -> None:
    rng = random.Random(0x5CE1E)
    for case_index in range(320):
        beats: list[StoryBeat] = []
        cursor = 0.0
        scene_count = rng.randint(1, 3)
        for scene_index in range(scene_count):
            asset_count = rng.randint(1, 25)
            beat_count = rng.randint(1, 10)
            asset_ids = [f"c{case_index}-s{scene_index}-a{i}" for i in range(asset_count)]
            unrevealed = list(asset_ids)
            for beat_index in range(beat_count):
                remaining_beats = beat_count - beat_index
                reveal_count = (
                    len(unrevealed)
                    if remaining_beats == 1
                    else rng.randint(0, min(len(unrevealed), max(1, len(unrevealed) // remaining_beats + 1)))
                )
                reveal = [unrevealed.pop(rng.randrange(len(unrevealed))) for _ in range(reveal_count)]
                duration = rng.choice((0.08, 0.18, 0.7, 2.0, 12.0))
                activations = [
                    AssetActivation(
                        asset_id=asset_id,
                        semantic_unit_id=asset_id,
                        semantic_event_id=f"event-{beat_index}",
                        semantic_event_roles=[rng.choice(("PRIMARY", "SUPPORT", "RESULT"))],
                        spoken_start=cursor,
                        spoken_end=cursor + duration,
                        confidence=1.0,
                        source="generated-test3",
                        policy="EXPLICIT",
                    )
                    for asset_id in reveal
                ]
                if rng.random() < 0.25:
                    activations.append(AssetActivation(
                        asset_id=f"abstain-{case_index}-{scene_index}-{beat_index}",
                        semantic_unit_id="SAFE",
                        spoken_start=cursor,
                        spoken_end=cursor + duration,
                        confidence=0.0,
                        source="generated-test3",
                        policy="SAFE_ABSTENTION",
                    ))
                beats.append(StoryBeat(
                    id=f"case-{case_index}-scene-{scene_index}-beat-{beat_index}",
                    scene_id=f"scene-{scene_index}",
                    start=cursor,
                    end=cursor + duration,
                    narration="generated lifecycle",
                    primary_asset_ids=reveal[:1],
                    support_asset_ids=reveal[1:],
                    action=rng.choice(("EXPLAIN", "COMPARE", "RESULT")),
                    asset_activations=activations,
                ))
                cursor += duration
        resolved = StoryPlanner._resolve_active_visual_semantic_state(beats)
        _assert_monotonic_scene_lifecycle(resolved)
        for beat in resolved:
            assert all(not asset_id.startswith("abstain-") for asset_id in (beat.active_visual_semantic_state or {}))


def test_transition_never_classifies_same_scene_persistence_as_outgoing(tmp_path: Path) -> None:
    story, _choreography, composition, _motion, _render_plan = _real_story_pipeline(tmp_path)
    layouts = {layout.beat_id: layout for layout in composition}
    policy = VisualTransitionPolicy()
    for previous, current in zip(story, story[1:]):
        decision = policy.decide(
            previous,
            layouts[previous.id],
            layouts[current.id],
            current_beat=current,
        )
        assert not (decision.persistent_asset_ids & decision.carry_outgoing_asset_ids)
        assert not decision.carry_outgoing_asset_ids


def test_renderer_visibility_window_is_derived_from_pipeline_continuity(tmp_path: Path) -> None:
    story, _choreography, composition, motion, _render_plan = _real_story_pipeline(tmp_path)
    layouts = {layout.beat_id: layout for layout in composition}
    cues = {(cue.beat_id, cue.asset_id): cue for cue in motion}
    policy = VisualTransitionPolicy()
    for previous, current in zip(story, story[1:]):
        persistent = policy.decide(
            previous, layouts[previous.id], layouts[current.id], current_beat=current
        ).persistent_asset_ids
        for asset_id in persistent:
            cue = cues[(current.id, asset_id)]
            duration = current.end - current.start
            reveal_start, _end, _fade = FFmpegRenderer._cue_window(
                beat=current,
                cue=cue,
                segment_start=current.start,
                duration=duration,
            )
            start, end = FFmpegRenderer.asset_visibility_window(
                cue=cue,
                segment_start=current.start,
                duration=duration,
                reveal_start=reveal_start,
                persistent=asset_id in persistent,
            )
            assert start == pytest.approx(0.0)
            assert end == pytest.approx(duration)
            assert cue.params["semantic_continuity"]["mode"] == "PERSIST"
            assert not ContinuityContract.has_terminal_exit(cues[(previous.id, asset_id)])


def _single_beat_event_pipeline(
    root: Path,
    *,
    asset_count: int = 3,
    event_count: int = 3,
    duration: float = 4.0,
    unrelated: bool = False,
    proxy_carrier: bool = False,
    planners=None,
):
    root.mkdir(parents=True, exist_ok=True)
    image_path = root / "scene.png"
    Image.new("RGBA", (96, 96), (255, 255, 255, 255)).save(image_path)
    tokens = [f"word{i}" for i in range(event_count)]
    script = " ".join(tokens)
    spans = []
    cursor = 0
    for token in tokens:
        spans.append((cursor, cursor + len(token)))
        cursor += len(token) + 1

    asset_ids = [f"asset-{index}" for index in range(asset_count)]
    units = tuple(
        CanonicalAsset(
            unit_id=asset_id,
            asset_id=asset_id,
            scene_id="scene",
            script_text=tokens[min(index, event_count - 1)],
            script_span=CanonicalScriptSpan(
                text=tokens[min(index, event_count - 1)],
                global_char_start=spans[min(index, event_count - 1)][0],
                global_char_end=spans[min(index, event_count - 1)][1],
            ),
            binding_type="EXPLICIT",
            semantic_event_id=f"E{min(index, event_count - 1) + 1}",
        )
        for index, asset_id in enumerate(asset_ids)
    )
    events = tuple(
        CanonicalSemanticEvent(
            semantic_event_id=f"E{index + 1}",
            scene_id="scene",
            script_text=tokens[index],
            script_span=CanonicalScriptSpan(
                text=tokens[index],
                global_char_start=spans[index][0],
                global_char_end=spans[index][1],
            ),
            sequence_order=index + 1,
            visual_leader_asset_id=asset_ids[min(index, asset_count - 1)],
            participant_asset_ids=(asset_ids[min(index, asset_count - 1)],),
            depends_on_event_ids=(
                () if unrelated or index == 0 else (f"E{index}",)
            ),
        )
        for index in range(event_count)
    )
    package = CanonicalPackage(
        root=root,
        package_id=root.name,
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
            semantic_events=events,
        ),),
    )
    step = (duration - 0.4) / max(1, event_count)
    words = [
        TranscriptWord(
            start=0.2 + index * step,
            end=min(duration - 0.05, 0.2 + index * step + min(0.28, step * 0.6)),
            text=token,
            char_start=spans[index][0],
            char_end=spans[index][1],
        )
        for index, token in enumerate(tokens)
    ]
    transcript = Transcript(
        duration=duration,
        segments=[],
        words=words,
        timing_source="forced_alignment",
    )
    runtime_ids = ["proxy-runtime"] if proxy_carrier else asset_ids
    assets = [
        VisualAsset(
            id=asset_id,
            scene_id="scene",
            role="object",
            image_path=image_path,
            extraction_method="test3-single-beat",
            source_bbox=(
                (24, 24, 48, 48)
                if proxy_carrier
                else (8 + index * 3, 8 + index * 3, 28, 28)
            ),
            source_canvas_width=96,
            source_canvas_height=96,
            source_area_ratio=0.08,
            can_animate_independently=True,
        )
        for index, asset_id in enumerate(runtime_ids)
    ]
    if proxy_carrier:
        package = package.model_copy(update={
            "scenes": (package.scenes[0].model_copy(update={
                "units": (units[0].model_copy(update={
                    "unit_id": "intent",
                    "asset_id": "intent",
                    "visual_locator": CanonicalVisualLocator(
                        cx=0.5, cy=0.5, width=0.5, height=0.5
                    ),
                }),),
                "semantic_events": tuple(
                    event.model_copy(update={
                        "visual_leader_asset_id": "intent",
                        "participant_asset_ids": ("intent",),
                    })
                    for event in events
                ),
            }),),
        })
    story_planner, choreography_planner, composition_planner, motion_planner = (
        planners
        if planners is not None
        else (
            StoryPlanner(),
            ChoreographyDirector(),
            CompositionPlanner(),
            MotionPlanner(),
        )
    )
    story = story_planner.plan(package, transcript, assets)
    assert len(story) == 1
    choreography = choreography_planner.plan(package, story, assets)
    composition = composition_planner.plan(story, assets, choreography)
    motion = motion_planner.plan(story, composition, choreography, assets)
    render_root = root / "render-plan"
    render_root.mkdir()
    render_plan, _ = RenderPlanner().compile(
        transcript, assets, story, composition, motion, render_root
    )
    return story, choreography, composition, motion, render_plan


def _assert_single_beat_renderer_lifecycle(story, motion) -> int:
    assert len(story) == 1
    beat = story[0]
    legitimate = set(beat.active_visual_semantic_state or {})
    assert legitimate
    cues = {cue.asset_id: cue for cue in motion}
    for asset_id in legitimate:
        cue = cues[asset_id]
        exits = [segment for segment in cue.segments if segment.phase == "EXIT"]
        assert exits == []
        start, _end, _fade = FFmpegRenderer._cue_window(
            beat=beat,
            cue=cue,
            segment_start=beat.start,
            duration=beat.end - beat.start,
        )
        visible = FFmpegRenderer.asset_visibility_window(
            cue=cue,
            segment_start=beat.start,
            duration=beat.end - beat.start,
            reveal_start=start,
            persistent=False,
        )
        assert visible == pytest.approx((start, beat.end - beat.start))
        samples = [index * (beat.end - beat.start) / 40 for index in range(41)]
        states = [visible[0] <= sample <= visible[1] for sample in samples]
        first = states.index(True)
        assert all(states[first:])
    return len(legitimate)


@pytest.mark.parametrize(
    "name,asset_count,event_count,duration,unrelated,proxy",
    [
        ("progressive", 3, 3, 4.0, False, False),
        ("character-icon-result", 4, 4, 5.0, False, False),
        ("event-handoff", 2, 2, 3.0, False, False),
        ("dependency-chain", 4, 4, 5.0, False, False),
        ("unrelated", 2, 2, 3.0, True, False),
        ("focus-transfer", 3, 5, 5.0, False, False),
        ("relation", 2, 3, 4.0, False, False),
        ("result-payoff", 3, 3, 4.0, False, False),
        ("dense", 20, 12, 8.0, False, False),
        ("short", 3, 3, 0.8, False, False),
        ("long", 8, 10, 12.0, False, False),
        ("same-visual-events", 1, 6, 6.0, False, False),
        ("compound-proxy", 1, 4, 4.0, False, True),
    ],
)
def test_real_single_beat_multi_event_lifecycle(
    tmp_path: Path,
    name: str,
    asset_count: int,
    event_count: int,
    duration: float,
    unrelated: bool,
    proxy: bool,
) -> None:
    story, choreography, _composition, motion, render_plan = _single_beat_event_pipeline(
        tmp_path / name,
        asset_count=asset_count,
        event_count=event_count,
        duration=duration,
        unrelated=unrelated,
        proxy_carrier=proxy,
    )
    assert len(choreography.directives[0].event_flows) == event_count
    assert render_plan.story == story
    assert render_plan.motion == motion
    _assert_single_beat_renderer_lifecycle(story, motion)


def test_production_handoff_shape_is_scene_held_without_semantic_release_exit(
    tmp_path: Path,
) -> None:
    story, choreography, _composition, motion, _render_plan = _single_beat_event_pipeline(
        tmp_path / "production-trace", asset_count=3, event_count=3
    )
    beat = story[0]
    assignments = MotionPlanner().event_flow.resolve_all(
        choreography.directives[0],
        ["asset-0", "asset-1", "asset-2"],
        semantic_event_by_asset={
            row.asset_id: row.semantic_event_id for row in beat.asset_activations
        },
    )
    lifetime = SemanticVisualLifetimeIndex.build(
        beat=beat,
        directive=choreography.directives[0],
        assignments=assignments,
    )
    decision = lifetime.for_asset("asset-0")
    assert decision is not None
    assert decision.reasons == ("scene_active_until_scene_end",)
    assert decision.keep_visible_through == pytest.approx(beat.end)
    cue = next(cue for cue in motion if cue.asset_id == "asset-0")
    assert cue.params["semantic_lifetime"]["mode"] == "SCENE_ACTIVE_UNTIL_SCENE_END"
    assert all(segment.phase != "EXIT" for segment in cue.segments)


def test_512_generated_single_beat_timelines_are_monotonic() -> None:
    rng = random.Random(0x51A6E)
    asset_lifecycles = 0
    for case_index in range(512):
        duration = rng.uniform(0.4, 12.0)
        asset_count = rng.randint(1, 25)
        event_count = rng.randint(1, 12)
        activations = []
        for asset_index in range(asset_count):
            reveal = rng.uniform(0.0, duration * 0.92)
            activations.append(StoryAssetActivation(
                asset_id=f"case-{case_index}-asset-{asset_index}",
                semantic_unit_id=f"unit-{asset_index}",
                semantic_event_id=f"event-{rng.randrange(event_count)}",
                activation_policy="OWN_WINDOW",
                phrase_start=reveal,
                phrase_end=min(duration, reveal + 0.08),
                reveal_start=reveal,
                semantic_peak=min(duration, reveal + 0.04),
                settle_at=min(duration, reveal + 0.08),
            ))
        activations.append(StoryAssetActivation(
            asset_id=f"case-{case_index}-safe-abstention",
            semantic_unit_id="SAFE",
            semantic_event_id="SAFE",
            activation_policy="SAFE_ABSTENTION",
        ))
        beat = StoryBeat(
            id=f"case-{case_index}",
            scene_id=f"scene-{case_index}",
            start=0.0,
            end=duration,
            narration="generated",
            action="EXPLAIN",
            asset_activations=activations,
        )
        resolved = StoryPlanner._resolve_active_visual_semantic_state([beat])[0]
        visible = set(resolved.active_visual_semantic_state or {})
        assert len(visible) == asset_count
        assert not any(asset_id.endswith("safe-abstention") for asset_id in visible)
        for activation in activations[:-1]:
            timeline = [
                sample >= float(activation.reveal_start)
                for sample in (duration * index / 64 for index in range(65))
            ]
            first = timeline.index(True)
            assert all(timeline[first:])
            asset_lifecycles += 1
    assert asset_lifecycles >= 512


def test_legacy_lifetime_without_semantic_scene_state_keeps_historical_fallback() -> None:
    beat = StoryBeat(
        id="legacy",
        scene_id="legacy-scene",
        start=0.0,
        end=2.0,
        narration="legacy",
        action="EXPLAIN",
        active_visual_semantic_state=None,
    )
    assert SemanticVisualLifetimeIndex.build(
        beat=beat, directive=None, assignments={}
    ).for_asset("legacy-asset") is None


def _package_shape_pipeline(root: Path, *, scene_count: int, event_count: int):
    root.mkdir(parents=True, exist_ok=True)
    image_path = root / "scene.png"
    Image.new("RGBA", (64, 64), (255, 255, 255, 255)).save(image_path)
    script_parts = [f"scene{index}" for index in range(scene_count)]
    script = " ".join(script_parts)
    scenes = []
    assets = []
    words = []
    char_cursor = 0
    for scene_index, token in enumerate(script_parts):
        start = char_cursor
        end = start + len(token)
        scene_id = f"scene-{scene_index:03d}"
        asset_id = f"asset-{scene_index:03d}"
        unit = CanonicalAsset(
            unit_id=asset_id,
            asset_id=asset_id,
            scene_id=scene_id,
            script_text=token,
            script_span=CanonicalScriptSpan(
                text=token, global_char_start=start, global_char_end=end
            ),
            binding_type="EXPLICIT",
            semantic_event_id=f"{scene_id}-E1",
        )
        events = tuple(
            CanonicalSemanticEvent(
                semantic_event_id=f"{scene_id}-E{event_index + 1}",
                scene_id=scene_id,
                script_text=token,
                script_span=CanonicalScriptSpan(
                    text=token, global_char_start=start, global_char_end=end
                ),
                sequence_order=event_index + 1,
                visual_leader_asset_id=asset_id,
                participant_asset_ids=(asset_id,),
                depends_on_event_ids=(
                    ()
                    if event_index == 0
                    else (f"{scene_id}-E{event_index}",)
                ),
            )
            for event_index in range(event_count)
        )
        scenes.append(CanonicalScene(
            id=scene_id,
            image_path=image_path,
            order=scene_index,
            script_char_start=start,
            script_char_end=end,
            units=(unit,),
            semantic_events=events,
        ))
        assets.append(VisualAsset(
            id=asset_id,
            scene_id=scene_id,
            role="object",
            image_path=image_path,
            extraction_method="test3-package-shape",
            source_bbox=(16, 16, 32, 32),
            source_canvas_width=64,
            source_canvas_height=64,
            source_area_ratio=0.25,
        ))
        word_start = 0.1 + scene_index * 0.5
        words.append(TranscriptWord(
            start=word_start,
            end=word_start + 0.28,
            text=token,
            char_start=start,
            char_end=end,
        ))
        char_cursor = end + 1
    package = CanonicalPackage(
        root=root,
        package_id=root.name,
        script=script,
        semantic_binding_schema_name="HEXA_ASSET_LEVEL_SEMANTIC_BINDINGS",
        semantic_bindings_present=True,
        scenes=tuple(scenes),
    )
    transcript = Transcript(
        duration=scene_count * 0.5 + 0.5,
        segments=[],
        words=words,
        timing_source="forced_alignment",
    )
    story = StoryPlanner().plan(package, transcript, assets)
    assert len(story) == scene_count
    assert all(
        len([beat for beat in story if beat.scene_id == scene.id]) == 1
        for scene in scenes
    )
    choreography = ChoreographyDirector().plan(package, story, assets)
    composition = CompositionPlanner().plan(story, assets, choreography)
    motion = MotionPlanner().plan(story, composition, choreography, assets)
    render_root = root / "render-plan"
    render_root.mkdir()
    render_plan, _ = RenderPlanner().compile(
        transcript, assets, story, composition, motion, render_root
    )
    return story, choreography, motion, render_plan


@pytest.mark.parametrize(
    "scene_count,event_count",
    [(35, 2), (40, 2), (35, 3), (40, 3)],
)
def test_final_package_shaped_single_beat_scene_lifecycles(
    tmp_path: Path, scene_count: int, event_count: int
) -> None:
    story, choreography, motion, render_plan = _package_shape_pipeline(
        tmp_path / f"package-{scene_count}-{event_count}",
        scene_count=scene_count,
        event_count=event_count,
    )
    assert len(choreography.directives) == scene_count
    assert all(len(row.event_flows) == event_count for row in choreography.directives)
    assert render_plan.story == story
    assert render_plan.motion == motion
    cues = {(cue.beat_id, cue.asset_id): cue for cue in motion}
    for previous, current in zip(story, story[1:]):
        assert previous.scene_id != current.scene_id
        assert set(previous.active_visual_semantic_state or {}).isdisjoint(
            current.active_visual_semantic_state or {}
        )
    for beat in story:
        asset_id = next(iter(beat.active_visual_semantic_state or {}))
        cue = cues[(beat.id, asset_id)]
        assert all(segment.phase != "EXIT" for segment in cue.segments)


def test_shared_planners_have_no_cross_package_lifecycle_state(tmp_path: Path) -> None:
    planners = (
        StoryPlanner(),
        ChoreographyDirector(),
        CompositionPlanner(),
        MotionPlanner(),
    )

    def run(name: str, assets: int, events: int):
        story, _choreography, _composition, motion, _render_plan = (
            _single_beat_event_pipeline(
                tmp_path / name,
                asset_count=assets,
                event_count=events,
                planners=planners,
            )
        )
        return (
            [beat.model_dump(exclude={"id"}) for beat in story],
            [cue.model_dump(exclude={"beat_id"}) for cue in motion],
        )

    a_first = run("a-first", 3, 4)
    b_second = run("b-second", 5, 6)
    b_first = run("b-first", 5, 6)
    a_second = run("a-second", 3, 4)
    assert a_first == a_second
    assert b_first == b_second
