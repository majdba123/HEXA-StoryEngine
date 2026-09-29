from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import pytest

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
from tests.test1.factory import deterministic_transcript
from tests.test2.support.sprint2_perceptual_oracle import (
    assert_sprint2_perceptual_contracts,
)

_REAL_PACKAGES = (
    "HEXA_BLACK_HAT_HACKER_AR_UNIFIED_FINAL_PACKAGE_2_0.zip",
    "HEXA_WHITE_HAT_HACKER_AR_UNIFIED_FINAL_PACKAGE_2_0.zip",
    "HEXA_GRAY_HAT_HACKER_AR_UNIFIED_FINAL_PACKAGE_2_0.zip",
    "HEXA_SCRIPT_KIDDIE_AR_UNIFIED_FINAL_PACKAGE_2_0.zip",
)


@dataclass(frozen=True, slots=True)
class RealPlanningResult:
    filename: str
    scenes: int
    semantic_assets: int
    semantic_events: int
    pass1_assets: int
    runtime_assets: int
    story_beats: int
    motion_cues: int


_REAL_RESULT_CACHE: dict[tuple[str, str], RealPlanningResult] = {}


def _corpus_root() -> Path | None:
    raw = os.getenv("HEXA_REAL_PACKAGE_CORPUS")
    if raw:
        return Path(raw)
    if os.getenv("HEXA_REQUIRE_REAL_PACKAGE_CORPUS") == "1":
        pytest.fail("REAL PACKAGE CERTIFICATION BLOCKED: HEXA_REAL_PACKAGE_CORPUS is unset")
    return None


def certify_real_package_to_render_plan(
    corpus: Path, filename: str, workspace: Path
) -> RealPlanningResult:
    """Certify one accepted package through the real structural runtime asset path.

    Timing is deterministic because this is structural/planning certification rather
    than audio-sync certification. Visual runtime assets are *not* synthetic semantic
    stand-ins: Vision + Pass1 run on the real authored scene images so relation and
    carrier behavior matches the engine's actual runtime representation.
    """

    key = (str(corpus.resolve()), filename)
    cached = _REAL_RESULT_CACHE.get(key)
    if cached is not None:
        return cached

    source = corpus / filename
    if not source.is_file():
        pytest.fail(f"REAL PACKAGE CERTIFICATION BLOCKED: missing {filename}")

    raw = FinalPackageLoader().load(source, workspace / "load")
    canonical = raw
    transcript = deterministic_transcript(canonical)

    detections = VisionService().analyze(canonical)
    assert detections, f"{filename}: Vision produced no structural detections"

    assets = CutoutService().extract(canonical, detections, workspace / "pass1")
    assert assets, f"{filename}: Pass1 produced no usable runtime assets"
    pass1_assets = len(assets)
    pipeline = StoryEnginePipeline.__new__(StoryEnginePipeline)
    pipeline.settings = type("Settings", (), {"refinement_mode": "pass2_vnext"})()
    pipeline.cutout_pass2 = Pass2CutoutService()
    pipeline.refinement = None
    assets = pipeline._apply_refinement(canonical, assets, workspace / "pass2")
    assert assets, f"{filename}: Pass2 produced no usable runtime assets"

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
    render_workspace = workspace / "render"
    render_workspace.mkdir(parents=True, exist_ok=True)
    plan, plan_path = RenderPlanner().compile(
        transcript,
        assets,
        story,
        composition,
        motion,
        render_workspace,
        text=text,
    )

    runtime_asset_ids = {asset.id for asset in assets}
    beat_ids = {beat.id for beat in story}
    assert plan_path.is_file()
    assert len(story) == len(canonical.scenes)
    assert composition and motion
    assert {asset.id for asset in plan.assets} == runtime_asset_ids
    assert all(item.asset_id in runtime_asset_ids for beat in composition for item in beat.items)
    assert all(cue.asset_id in runtime_asset_ids and cue.beat_id in beat_ids for cue in motion)
    assert all(cue.beat_id in beat_ids for cue in text.cues)
    assert_sprint2_perceptual_contracts(
        canonical,
        story,
        composition,
        motion,
        plan,
    )

    result = RealPlanningResult(
        filename=filename,
        scenes=len(canonical.scenes),
        semantic_assets=len(canonical.asset_by_id),
        semantic_events=len(canonical.event_by_id),
        pass1_assets=pass1_assets,
        runtime_assets=len(assets),
        story_beats=len(story),
        motion_cues=len(motion),
    )
    _REAL_RESULT_CACHE[key] = result
    return result


@pytest.mark.parametrize("filename", _REAL_PACKAGES)
def test_real_package_reaches_render_plan_structurally(tmp_path: Path, filename: str) -> None:
    corpus = _corpus_root()
    if corpus is None:
        pytest.skip("real Final Package corpus is not installed in this CI environment")

    result = certify_real_package_to_render_plan(corpus, filename, tmp_path / filename)
    assert result.scenes > 0
    assert result.semantic_assets > 0
    assert result.semantic_events > 0
    assert result.pass1_assets > 0
    assert result.runtime_assets > 0
    assert result.story_beats == result.scenes
    assert result.motion_cues == result.runtime_assets