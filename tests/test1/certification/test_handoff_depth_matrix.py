from __future__ import annotations

from pathlib import Path

import pytest

from app.canonical import CanonicalNormalizer
from app.choreography import ChoreographyDirector
from app.composition import CompositionPlanner, TextCompositionPlanner
from app.shared.handoff import LayerHandoffValidator
from app.final_package import FinalPackageLoader
from app.models import Transcript
from app.motion import MotionPlanner, TextMotionPlanner
from app.render import RenderPlanner
from app.shared.errors import StageFailedError
from app.story import StoryPlanner
from app.text import TextPlanner
from tests.test1.factory import (
    DiskPackageShape,
    controlled_visual_assets,
    deterministic_transcript,
    seeded_disk_shape,
    write_valid_package,
)


def _scaled_transcript(transcript: Transcript, duration: float) -> Transcript:
    factor = duration / transcript.duration
    words = [
        word.model_copy(update={"start": word.start * factor, "end": word.end * factor})
        for word in transcript.words
    ]
    by_span = {(word.char_start, word.char_end): word for word in words}
    segments = []
    for segment in transcript.segments:
        segment_words = [by_span[(word.char_start, word.char_end)] for word in segment.words]
        segments.append(
            segment.model_copy(
                update={
                    "start": segment.start * factor,
                    "end": segment.end * factor,
                    "words": segment_words,
                }
            )
        )
    return transcript.model_copy(
        update={"duration": duration, "words": words, "segments": segments}
    )


def _full_planning_handoff(tmp_path: Path, shape: DiskPackageShape):
    source = write_valid_package(tmp_path / "source", shape)
    raw = FinalPackageLoader().load(source, tmp_path / "work")
    package = CanonicalNormalizer().normalize(raw)
    transcript = deterministic_transcript(package)
    assets = controlled_visual_assets(package)
    contracts = LayerHandoffValidator()

    contracts.require_assets_for_story(package=package, assets=assets)
    story = StoryPlanner().plan(package, transcript, assets)
    contracts.require_story_for_choreography(
        package=package, transcript=transcript, assets=assets, story=story
    )
    choreography = ChoreographyDirector().plan(package, story, assets)
    contracts.require_choreography_for_composition(
        story=story, assets=assets, choreography=choreography
    )
    composition = CompositionPlanner().plan(story, assets, choreography)
    contracts.require_composition_for_motion(
        story=story, assets=assets, composition=composition
    )
    motion = MotionPlanner().plan(story, composition, choreography, assets)
    contracts.require_motion_for_text_and_render(
        story=story,
        assets=assets,
        composition=composition,
        choreography=choreography,
        motion=motion,
    )
    text = TextPlanner().plan(
        transcript=transcript,
        story=story,
        assets=assets,
        package=package,
        choreography=choreography,
    )
    contracts.require_text_for_composition(
        transcript=transcript, story=story, assets=assets, text=text
    )
    text_composition = TextCompositionPlanner().plan(
        story,
        composition,
        text.cues,
        assets,
        visual_motion=motion,
    )
    accepted_ids = {
        item.text_cue_id for beat in text_composition for item in beat.items
    }
    text = text.model_copy(
        update={"cues": [cue for cue in text.cues if cue.id in accepted_ids]}
    )
    text_motion = TextMotionPlanner().plan(
        story,
        text.cues,
        text_composition,
        choreography,
        visual_motion=motion,
    )
    contracts.require_text_render_contract(
        story=story,
        assets=assets,
        text=text,
        text_composition=text_composition,
        text_motion=text_motion,
    )
    render_workspace = tmp_path / "render"
    render_workspace.mkdir()
    render_plan, path = RenderPlanner().compile(
        transcript,
        assets,
        story,
        composition,
        motion,
        render_workspace,
        text=text,
        text_composition=text_composition,
        text_motion=text_motion,
    )
    return render_plan, path


FULL_TEXT_HANDOFF_SEEDS = tuple(range(6101, 6121))


@pytest.mark.parametrize("seed", FULL_TEXT_HANDOFF_SEEDS)
def test_seeded_packages_cross_every_planning_handoff_through_renderplan(
    tmp_path: Path, seed: int
) -> None:
    plan, path = _full_planning_handoff(tmp_path, seeded_disk_shape(seed))
    assert path.is_file()
    assert plan.story
    assert plan.composition
    assert plan.motion
    assert {
        item.text_cue_id for beat in plan.text_composition for item in beat.items
    } == {cue.id for cue in plan.text.cues}
    assert {cue.text_cue_id for cue in plan.text_motion} == {cue.id for cue in plan.text.cues}


@pytest.mark.parametrize(
    ("assets_per_scene", "duration"),
    [
        (1, 0.5),
        (1, 1.5),
        (5, 1.5),
        (5, 3.0),
        (20, 3.0),
        (20, 8.0),
    ],
    ids=["1x500ms", "1x1500ms", "5x1500ms", "5x3s", "20x3s", "20x8s"],
)
def test_duration_density_matrix_remains_cross_layer_executable(
    tmp_path: Path,
    assets_per_scene: int,
    duration: float,
) -> None:
    shape = DiskPackageShape(
        scenes=1,
        assets_per_scene=assets_per_scene,
        relations=True,
        dependencies=True,
        dependency_mode="linear",
        locators="partial",
        group_count=2,
        reuse_first_asset=True,
        script_style="arabic" if assets_per_scene > 1 else "numbers",
    )
    source = write_valid_package(tmp_path / "source", shape)
    package = CanonicalNormalizer().normalize(
        FinalPackageLoader().load(source, tmp_path / "work")
    )
    transcript = _scaled_transcript(deterministic_transcript(package), duration)
    assets = controlled_visual_assets(package)
    contracts = LayerHandoffValidator()

    contracts.require_assets_for_story(package=package, assets=assets)
    story = StoryPlanner().plan(package, transcript, assets)
    contracts.require_story_for_choreography(
        package=package, transcript=transcript, assets=assets, story=story
    )
    choreography = ChoreographyDirector().plan(package, story, assets)
    contracts.require_choreography_for_composition(
        story=story, assets=assets, choreography=choreography
    )
    composition = CompositionPlanner().plan(story, assets, choreography)
    contracts.require_composition_for_motion(
        story=story, assets=assets, composition=composition
    )
    motion = MotionPlanner().plan(story, composition, choreography, assets)
    contracts.require_motion_for_text_and_render(
        story=story,
        assets=assets,
        composition=composition,
        choreography=choreography,
        motion=motion,
    )
    assert len(motion) == assets_per_scene


@pytest.mark.parametrize(
    ("assets_per_scene", "duration", "expected_code"),
    [
        (5, 0.5, "MISSING_TARGET_REACTION"),
        (20, 0.5, "MISSING_RELATION_TIMELINE"),
    ],
    ids=["dense-5-fast-fail-closed", "dense-20-fast-fail-closed"],
)
def test_physically_impossible_density_fails_before_render(
    tmp_path: Path,
    assets_per_scene: int,
    duration: float,
    expected_code: str,
) -> None:
    source = write_valid_package(
        tmp_path / "source",
        DiskPackageShape(
            scenes=1,
            assets_per_scene=assets_per_scene,
            relations=True,
            dependencies=True,
            dependency_mode="linear",
            locators="partial",
            group_count=2,
            reuse_first_asset=True,
            script_style="arabic",
        ),
    )
    package = CanonicalNormalizer().normalize(
        FinalPackageLoader().load(source, tmp_path / "work")
    )
    transcript = _scaled_transcript(deterministic_transcript(package), duration)
    assets = controlled_visual_assets(package)
    story = StoryPlanner().plan(package, transcript, assets)
    choreography = ChoreographyDirector().plan(package, story, assets)
    composition = CompositionPlanner().plan(story, assets, choreography)

    with pytest.raises(StageFailedError) as exc_info:
        MotionPlanner().plan(story, composition, choreography, assets)
    assert exc_info.value.effective_code == expected_code
