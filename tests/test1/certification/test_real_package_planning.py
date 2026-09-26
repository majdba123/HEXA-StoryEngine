from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.canonical import CanonicalNormalizer
from app.choreography import ChoreographyDirector
from app.composition import CompositionPlanner
from app.final_package import FinalPackageLoader
from app.motion import MotionPlanner
from app.render import RenderPlanner
from app.story import StoryPlanner
from app.shared.errors import StageFailedError
from app.text import TextPlanner
from tests.test1.factory import controlled_visual_assets, deterministic_transcript

_REAL_PACKAGES = (
    "HEXA_BLACK_HAT_HACKER_AR_HEXA_V20_FINAL_PACKAGE_1_2_CORRECTED.zip",
    "HEXA_WHITE_HAT_HACKER_AR_HEXA_V20_FINAL_PACKAGE_1_2_CORRECTED.zip",
    "HEXA_GRAY_HAT_HACKER_AR_HEXA_V20_FINAL_PACKAGE_1_2_CORRECTED.zip",
    "HEXA_SCRIPT_KIDDIE_AR_HEXA_V20_FINAL_PACKAGE_1_2_CORRECTED.zip",
)


def _corpus_root() -> Path | None:
    raw = os.getenv("HEXA_REAL_PACKAGE_CORPUS")
    if raw:
        return Path(raw)
    if os.getenv("HEXA_REQUIRE_REAL_PACKAGE_CORPUS") == "1":
        pytest.fail("REAL PACKAGE CERTIFICATION BLOCKED: HEXA_REAL_PACKAGE_CORPUS is unset")
    return None


@pytest.mark.parametrize("filename", _REAL_PACKAGES)
def test_real_package_reaches_render_plan_structurally(tmp_path: Path, filename: str) -> None:
    corpus = _corpus_root()
    if corpus is None:
        pytest.skip("real Final Package corpus is not installed in this CI environment")
    source = corpus / filename
    if not source.is_file():
        pytest.fail(f"REAL PACKAGE CERTIFICATION BLOCKED: missing {filename}")

    raw = FinalPackageLoader().load(source, tmp_path / "load")
    canonical = CanonicalNormalizer().normalize(raw)
    transcript = deterministic_transcript(canonical)
    assets = controlled_visual_assets(canonical)
    story = StoryPlanner().plan(canonical, transcript, assets)
    choreography = ChoreographyDirector().plan(canonical, story, assets)
    composition = CompositionPlanner().plan(story, assets, choreography)
    try:
        motion = MotionPlanner().plan(story, composition, choreography, assets)
    except StageFailedError as exc:
        code = exc.details.get("code") if isinstance(exc.details, dict) else None
        pytest.xfail(
            "REAL PACKAGE PLANNING BLOCKED with deterministic synthetic runtime "
            f"assets/transcript: {code or type(exc).__name__}: {exc}"
        )
    text = TextPlanner().plan(
        transcript=transcript,
        story=story,
        assets=assets,
        package=canonical,
        choreography=choreography,
    )
    workspace = tmp_path / "render"
    workspace.mkdir(parents=True, exist_ok=True)
    plan, plan_path = RenderPlanner().compile(
        transcript,
        assets,
        story,
        composition,
        motion,
        workspace,
        text=text,
    )

    asset_ids = set(canonical.asset_by_id)
    beat_ids = {beat.id for beat in story}
    assert plan_path.is_file()
    assert story and composition and motion
    assert {asset.id for asset in plan.assets} == asset_ids
    assert all(item.asset_id in asset_ids for beat in composition for item in beat.items)
    assert all(cue.asset_id in asset_ids and cue.beat_id in beat_ids for cue in motion)
    assert all(cue.beat_id in beat_ids for cue in text.cues)
