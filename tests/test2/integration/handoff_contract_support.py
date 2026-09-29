from __future__ import annotations

from pathlib import Path

import pytest

from app.choreography import ChoreographyDirector
from app.composition import CompositionPlanner
from app.final_package import FinalPackageLoader
from app.motion import MotionPlanner
from app.shared.errors import StageFailedError
from app.story import StoryPlanner
from app.text import TextPlanner
from tests.test1.factory import (
    DiskPackageShape,
    controlled_visual_assets,
    deterministic_transcript,
    write_valid_package,
)


def build_handoff_case(tmp_path: Path, *, namespace: str = "HANDOFF"):
    source = write_valid_package(
        tmp_path / "source",
        DiskPackageShape(
            scenes=2,
            assets_per_scene=4,
            relations=True,
            dependencies=True,
            dependency_mode="branching",
            locators="partial",
            compound=True,
            progression=True,
            group_count=2,
            reuse_first_asset=True,
            script_style="numbers",
            namespace=namespace,
        ),
    )
    package = FinalPackageLoader().load(source, tmp_path / "work")
    transcript = deterministic_transcript(package)
    assets = controlled_visual_assets(package)
    story = StoryPlanner().plan(package, transcript, assets)
    choreography = ChoreographyDirector().plan(package, story, assets)
    composition = CompositionPlanner().plan(story, assets, choreography)
    motion = MotionPlanner().plan(story, composition, choreography, assets)
    text = TextPlanner().plan(
        transcript=transcript,
        story=story,
        assets=assets,
        package=package,
        choreography=choreography,
    )
    return package, transcript, assets, story, choreography, composition, motion, text


def expect_handoff_failure(code: str, call) -> StageFailedError:
    with pytest.raises(StageFailedError) as exc_info:
        call()
    assert exc_info.value.effective_code == code
    assert exc_info.value.details["violation_count"] >= 1
    assert exc_info.value.details["violations"]
    return exc_info.value
