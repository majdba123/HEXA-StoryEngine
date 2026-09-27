from __future__ import annotations

from pathlib import Path

import pytest

from app.composition import CompositionPlanner
from app.models import StoryBeat, VisualAsset
from app.shared.errors import StageFailedError


def _asset(asset_id: str, *, x: float = 0.1) -> VisualAsset:
    return VisualAsset(
        id=asset_id,
        scene_id="scene-1",
        role="primary",
        image_path=Path(f"{asset_id}.png"),
        extraction_method="test2",
        source_bbox=(round(x * 1000), 100, 80, 80),
        source_canvas_width=1000,
        source_canvas_height=1000,
        can_animate_independently=True,
    )


def _beat() -> StoryBeat:
    return StoryBeat(
        id="beat-1",
        scene_id="scene-1",
        start=0.0,
        end=1.0,
        narration="test",
        action="INTRODUCE",
        primary_asset_ids=["a"],
        support_asset_ids=["b"],
    )


@pytest.mark.parametrize("count", [1, 2, 20])
def test_composition_preserves_every_independently_animatable_asset(count: int) -> None:
    assets = [_asset(f"asset-{index}", x=min(0.75, index * 0.02)) for index in range(count)]
    layouts = CompositionPlanner().plan([_beat()], assets)
    assert {item.asset_id for item in layouts[0].items} == {asset.id for asset in assets}


def test_composition_fails_closed_when_owner_drops_an_asset(monkeypatch) -> None:
    planner = CompositionPlanner()
    assets = [_asset("a"), _asset("b", x=0.4)]
    original = planner._scene_layout
    monkeypatch.setattr(planner, "_scene_layout", lambda rows: original(rows)[:1])
    with pytest.raises(StageFailedError) as exc:
        planner.plan([_beat()], assets)
    assert exc.value.details["code"] == "ASSET_REACHES_COMPOSITION"


def test_composition_rejects_geometry_that_solver_reports_invalid(monkeypatch) -> None:
    planner = CompositionPlanner()
    monkeypatch.setattr(planner.solver, "inspect", lambda *_: ["offscreen:a"])
    with pytest.raises(StageFailedError) as exc:
        planner.plan([_beat()], [_asset("a")])
    assert exc.value.details["code"] == "LAYOUT_REFERENCE_VIOLATION"
