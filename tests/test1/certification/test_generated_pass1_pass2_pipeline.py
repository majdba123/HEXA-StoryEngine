from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

from PIL import Image, ImageDraw

from app.canonical import CanonicalNormalizer
from app.choreography import ChoreographyDirector
from app.composition import CompositionPlanner
from app.cutout import CutoutService, Pass2CutoutService
from app.final_package import FinalPackageLoader
from app.motion import MotionPlanner
from app.pipeline import StoryEnginePipeline
from app.render import RenderPlanner
from app.story import StoryPlanner
from app.text import TextPlanner
from app.vision import VisionService
from tests.test1.factory import DiskPackageShape, deterministic_transcript, write_valid_package


def test_generated_package_runs_real_pass1_pass2_to_render_plan(tmp_path: Path) -> None:
    package_root = write_valid_package(
        tmp_path / "source",
        DiskPackageShape(
            scenes=1,
            assets_per_scene=2,
            relations=False,
            dependencies=False,
            locators="all",
        ),
    )
    scene_path = package_root / "scenes" / "SCENE_001.png"
    image = Image.new("RGB", (320, 180), "white")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((28, 35, 125, 145), radius=12, fill="#1473e6", outline="#05295c", width=5)
    draw.ellipse((202, 48, 286, 132), fill="#f05a28", outline="#702000", width=5)
    image.save(scene_path)

    raw = FinalPackageLoader().load(package_root, tmp_path / "load")
    canonical = CanonicalNormalizer().normalize(raw)
    canonical_snapshot = deepcopy(canonical.model_dump())
    detections = VisionService().analyze(canonical)
    assert len(detections) == 2

    pass1 = CutoutService().extract(canonical, detections, tmp_path / "runtime")
    assert len(pass1) == 2
    assert all(asset.image_path.is_file() for asset in pass1)

    pipeline = StoryEnginePipeline.__new__(StoryEnginePipeline)
    pipeline.settings = SimpleNamespace(refinement_mode="pass2_vnext")
    pipeline.cutout_pass2 = Pass2CutoutService()
    pipeline.refinement = None
    assets = pipeline._apply_refinement(canonical, pass1, tmp_path / "runtime")
    assert [asset.id for asset in assets[:2]] == [asset.id for asset in pass1]

    transcript = deterministic_transcript(canonical)
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
    render_workspace.mkdir()
    plan, plan_path = RenderPlanner().compile(
        transcript,
        assets,
        story,
        composition,
        motion,
        render_workspace,
        text=text,
    )

    assert plan_path.is_file()
    assert [asset.id for asset in plan.assets] == [asset.id for asset in assets]
    assert len(plan.story) == 1
    assert plan.composition and plan.motion
    assert canonical.model_dump() == canonical_snapshot
