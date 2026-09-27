from __future__ import annotations
# Owner-scoped Test2 coverage; historical regression content is preserved.

from pathlib import Path

import pytest

from app.models import CompositionBeat, LayoutItem, MotionCue, StoryBeat, Transcript, VisualAsset
from app.render import RenderPlanner
from app.shared.errors import StageFailedError


def _asset(tmp_path: Path) -> VisualAsset:
    path = tmp_path / "asset.png"
    path.write_bytes(b"asset")
    return VisualAsset(
        id="asset-1",
        scene_id="scene-1",
        role="primary",
        image_path=path,
        extraction_method="test",
    )


def _compile(
    tmp_path: Path,
    *,
    asset: VisualAsset,
    beat: StoryBeat,
    composition: list[CompositionBeat] | None = None,
    motion: list[MotionCue] | None = None,
):
    workspace = tmp_path / "render"
    workspace.mkdir()
    return RenderPlanner().compile(
        Transcript(language="en", duration=1.0, segments=[], words=[]),
        [asset],
        [beat],
        composition or [],
        motion or [],
        workspace,
    )


def test_render_plan_rejects_missing_asset_file(tmp_path: Path) -> None:
    asset = _asset(tmp_path)
    asset.image_path.unlink()
    beat = StoryBeat(
        id="beat-1",
        scene_id="scene-1",
        start=0.0,
        end=1.0,
        narration="test",
        action="EXPLAIN",
        primary_asset_ids=[asset.id],
    )

    with pytest.raises(StageFailedError) as caught:
        _compile(tmp_path, asset=asset, beat=beat)

    assert caught.value.effective_code == "ASSET_BAD_CUTOUT"


def test_render_plan_rejects_unknown_story_asset(tmp_path: Path) -> None:
    asset = _asset(tmp_path)
    beat = StoryBeat(
        id="beat-1",
        scene_id="scene-1",
        start=0.0,
        end=1.0,
        narration="test",
        action="EXPLAIN",
        primary_asset_ids=["unknown"],
    )

    with pytest.raises(StageFailedError) as caught:
        _compile(tmp_path, asset=asset, beat=beat)

    assert caught.value.effective_code == "ASSET_BAD_CUTOUT"
    assert caught.value.details["asset_id"] == "unknown"


def test_render_plan_rejects_handoff_without_source(tmp_path: Path) -> None:
    asset = _asset(tmp_path)
    beat = StoryBeat(
        id="beat-1",
        scene_id="scene-1",
        start=0.0,
        end=1.0,
        narration="test",
        action="HANDOFF",
        primary_asset_ids=[asset.id],
    )

    with pytest.raises(StageFailedError) as caught:
        _compile(tmp_path, asset=asset, beat=beat)

    assert caught.value.effective_code == "BAD_HANDOFF"


def test_render_plan_accepts_resolved_references(tmp_path: Path) -> None:
    asset = _asset(tmp_path)
    beat = StoryBeat(
        id="beat-1",
        scene_id="scene-1",
        start=0.0,
        end=1.0,
        narration="test",
        action="EXPLAIN",
        primary_asset_ids=[asset.id],
    )
    plan, path = _compile(
        tmp_path,
        asset=asset,
        beat=beat,
        composition=[CompositionBeat(
            beat_id=beat.id,
            items=[LayoutItem(asset_id=asset.id, x=0.5, y=0.5, width=0.3, height=0.3)],
        )],
        motion=[MotionCue(
            beat_id=beat.id,
            asset_id=asset.id,
            kind="hold",
            start=0.0,
            end=1.0,
        )],
    )

    assert path.is_file()
    assert plan.assets[0].id == asset.id
