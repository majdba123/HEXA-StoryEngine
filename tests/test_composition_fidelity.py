from pathlib import Path

import pytest

from app.composition.planner import CompositionPlanner
from app.models import StoryBeat, VisualAsset


def test_source_geometry_is_preserved_without_relayout(tmp_path: Path) -> None:
    a = VisualAsset(
        id="a",
        scene_id="scene",
        role="primary",
        image_path=tmp_path / "a.png",
        extraction_method="test",
        source_bbox=(100, 100, 200, 200),
        source_canvas_width=1000,
        source_canvas_height=562,
    )
    b = VisualAsset(
        id="b",
        scene_id="scene",
        role="support",
        image_path=tmp_path / "b.png",
        extraction_method="test",
        source_bbox=(700, 200, 150, 180),
        source_canvas_width=1000,
        source_canvas_height=562,
    )
    beat = StoryBeat(
        id="beat",
        scene_id="scene",
        start=0.0,
        end=2.0,
        narration="test",
        primary_asset_ids=["a"],
        support_asset_ids=["b"],
        action="INTRODUCE",
    )

    composition = CompositionPlanner().plan([beat], [a, b])[0]
    first, second = composition.items

    assert first.x == pytest.approx(0.20, abs=0.003)
    assert first.y == pytest.approx(200 / 562, abs=0.003)
    assert first.width == pytest.approx(0.20, abs=0.003)
    assert second.x == pytest.approx(0.775, abs=0.003)
    assert second.width == pytest.approx(0.15, abs=0.003)
