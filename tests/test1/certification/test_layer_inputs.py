from pathlib import Path

from app.canonical import CanonicalNormalizer
from app.choreography import ChoreographyDirector
from app.composition import CompositionPlanner
from app.models import Transcript, TranscriptWord, VisualAsset
from app.motion import MotionPlanner
from app.render import RenderPlanner
from app.story import StoryPlanner
from app.text import TextPlanner
from tests.test1.factory import make_package


def test_story_choreography_text_accept_canonical_package(tmp_path: Path) -> None:
    legacy = make_package(
        tmp_path, scene_count=1, assets_per_scene=1, events_per_scene=1,
        with_relations=False, with_locators=False,
    )
    canonical = CanonicalNormalizer().normalize(legacy)
    scene = canonical.scenes[0]
    script = canonical.script or ""
    word = script.split()[0]
    transcript = Transcript(
        duration=1.0,
        segments=[],
        words=[TranscriptWord(start=0.1, end=0.4, text=word, char_start=0, char_end=len(word))],
    )
    asset_id = next(iter(canonical.asset_by_id))
    assets = [VisualAsset(
        id=asset_id,
        scene_id=scene.id,
        role="primary",
        image_path=scene.image_path,
        extraction_method="test",
        source_area_ratio=0.2,
    )]
    story = StoryPlanner().plan(canonical, transcript, assets)
    choreography = ChoreographyDirector().plan(canonical, story, assets)
    text = TextPlanner().plan(
        transcript=transcript, story=story, assets=assets,
        package=canonical, choreography=choreography,
    )
    assert story
    assert choreography.directives
    composition = CompositionPlanner().plan(story, assets, choreography)
    motion = MotionPlanner().plan(story, composition, choreography, assets)
    render_workspace = tmp_path / "render"
    render_workspace.mkdir(parents=True)
    render_plan, render_path = RenderPlanner().compile(
        transcript=transcript,
        assets=assets,
        story=story,
        composition=composition,
        motion=motion,
        workspace=render_workspace,
        text=text,
    )
    assert text is not None
    assert composition
    assert motion
    assert render_plan.story == story
    assert render_plan.composition == composition
    assert render_plan.motion == motion
    assert render_path.is_file()
