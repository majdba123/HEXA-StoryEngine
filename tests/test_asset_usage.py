from pathlib import Path

import pytest

from app.diagnostics import AssetUsageValidator
from app.models import (
    CompositionBeat,
    LayoutItem,
    MotionCue,
    RenderPlan,
    StoryBeat,
    VisualAsset,
)
from app.shared.errors import StageFailedError


def _plan(*, include_second_motion: bool = True) -> RenderPlan:
    assets = [
        VisualAsset(
            id="a1", scene_id="s1", role="primary", image_path=Path("a1.png"),
            extraction_method="fixture",
        ),
        VisualAsset(
            id="a2", scene_id="s1", role="support", image_path=Path("a2.png"),
            extraction_method="pass2_secondary",
        ),
    ]
    beat = StoryBeat(
        id="b1", scene_id="s1", start=0.0, end=1.0, narration="test",
        primary_asset_ids=["a1"], support_asset_ids=["a2"], action="INTRODUCE",
    )
    motion = [MotionCue(beat_id="b1", asset_id="a1", kind="soft_in", start=0.0, end=0.2)]
    if include_second_motion:
        motion.append(MotionCue(beat_id="b1", asset_id="a2", kind="soft_in", start=0.2, end=0.4))
    return RenderPlan(
        duration=1.0,
        story=[beat],
        composition=[CompositionBeat(beat_id="b1", items=[
            LayoutItem(asset_id="a1", x=0.4, y=0.5, width=0.3, height=0.3),
            LayoutItem(asset_id="a2", x=0.7, y=0.5, width=0.2, height=0.2),
        ])],
        motion=motion,
        assets=assets,
    )


def test_asset_usage_requires_every_separated_asset_in_motion() -> None:
    report = AssetUsageValidator.validate(_plan())
    assert report.complete
    assert report.eligible_assets == 2
    assert report.motion_used == 2


def test_asset_usage_fails_closed_when_motion_drops_cutout() -> None:
    with pytest.raises(StageFailedError) as exc:
        AssetUsageValidator.validate(_plan(include_second_motion=False))
    assert "a2" in exc.value.details["missing_motion"]
