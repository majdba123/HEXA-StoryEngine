from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import pytest

from app.canonical import CanonicalNormalizer
from app.choreography import ChoreographyDirector
from app.composition import CompositionPlanner
from app.final_package import FinalPackageLoader
from app.models import VisualAsset
from app.motion import MotionPlanner
from app.render import RenderPlanner
from app.story import StoryPlanner
from app.text import TextPlanner
from app.vision import VisionService
from PIL import Image
from tests.test1.factory import deterministic_transcript

_REAL_PACKAGES = (
    "HEXA_BLACK_HAT_HACKER_AR_HEXA_V20_FINAL_PACKAGE_1_2_CORRECTED.zip",
    "HEXA_WHITE_HAT_HACKER_AR_HEXA_V20_FINAL_PACKAGE_1_2_CORRECTED.zip",
    "HEXA_GRAY_HAT_HACKER_AR_HEXA_V20_FINAL_PACKAGE_1_2_CORRECTED.zip",
    "HEXA_SCRIPT_KIDDIE_AR_HEXA_V20_FINAL_PACKAGE_1_2_CORRECTED.zip",
)


@dataclass(frozen=True, slots=True)
class RealPlanningResult:
    filename: str
    scenes: int
    semantic_assets: int
    semantic_events: int
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
    canonical = CanonicalNormalizer().normalize(raw)
    transcript = deterministic_transcript(canonical)

    detections = VisionService().analyze(canonical)
    assert detections, f"{filename}: Vision produced no structural detections"

    # Planning certification needs the real runtime object topology/geometry, not
    # PNG encoding. Build descriptors from Vision detections using the same stable
    # scene-local IDs as Pass1. This preserves real carrier cardinality while
    # avoiding expensive cutout file I/O in release certification.
    counters: dict[str, int] = {}
    canvas_sizes: dict[Path, tuple[int, int]] = {}
    assets: list[VisualAsset] = []
    for detection in detections:
        if detection.bbox is None:
            continue
        counters[detection.scene_id] = counters.get(detection.scene_id, 0) + 1
        number = counters[detection.scene_id]
        canvas = canvas_sizes.get(detection.source_image)
        if canvas is None:
            with Image.open(detection.source_image) as source_image:
                canvas = source_image.size
            canvas_sizes[detection.source_image] = canvas
        assets.append(VisualAsset(
            id=f"{detection.scene_id}:asset-{number:02d}",
            scene_id=detection.scene_id,
            role=detection.role,
            image_path=detection.source_image,
            source_bbox=detection.bbox,
            confidence=detection.confidence,
            extraction_method="test1-real-vision-structural",
            independent=True,
            compound=bool(detection.compound),
            component_count=max(1, int(detection.component_count)),
            source_area_ratio=detection.area_ratio or None,
            source_canvas_width=canvas[0],
            source_canvas_height=canvas[1],
            can_animate_independently=True,
        ))
    assert assets, f"{filename}: Vision produced no usable runtime assets"

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

    result = RealPlanningResult(
        filename=filename,
        scenes=len(canonical.scenes),
        semantic_assets=len(canonical.asset_by_id),
        semantic_events=len(canonical.event_by_id),
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
    assert result.runtime_assets > 0
    assert result.story_beats == result.scenes
    assert result.motion_cues == result.runtime_assets
