"""Retained legacy reflow policy; production Reels uses reference projection."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from PIL import Image

from app.choreography import ChoreographyDirective, RelationFlowDecision, RelationTreatment
from app.choreography.models import SequencePhase
from app.composition import CompositionPlanner
from app.models import LayoutItem, VisualAsset
from app.targets import REELS_9_16, YOUTUBE_16_9, composition_policy, visual_target
from app.targets.reels.composition import REFLOW_PLACEMENT_SOURCE
from app.targets.reels.safe_zones import REELS_ART_REGION

W, H = REELS_9_16.frame
LEGACY_REFLOW = replace(
    REELS_9_16, layout_policy="responsive_portrait",
    layout_options={"contact_px": 0.0, "gap_px": 64.0,
                    "related_gap_px": 120.0, "max_scale": 1.0},
)


def _asset(tmp: Path, asset_id: str, *, family: str | None = None) -> VisualAsset:
    path = tmp / f"{asset_id.replace(':', '_')}.png"
    Image.new("RGBA", (40, 40), (20, 20, 20, 255)).save(path)
    return VisualAsset(
        id=asset_id, scene_id="s1", role="primary", image_path=path,
        extraction_method="test", asset_family_id=family,
    )


def _item(asset_id: str, x: float, y: float, w: float, h: float, z: int = 10) -> LayoutItem:
    return LayoutItem(asset_id=asset_id, x=x, y=y, width=w, height=h, z=z,
                      placement_source="authored_scene_geometry")


def _relation(source: str, target: str) -> ChoreographyDirective:
    return ChoreographyDirective(
        beat_id="b1", sequence_id="q", phase=SequencePhase.SETUP, action="REVEAL",
        primary_asset_id=source,
        relation_flows=(RelationFlowDecision(
            relationship="CAUSES", source_asset_id=source, target_asset_id=target,
            treatment=RelationTreatment.INTERACTION, reason="test",
        ),),
    )


def _px_box(item: LayoutItem) -> tuple[float, float, float, float]:
    return ((item.x - item.width / 2) * W, (item.y - item.height / 2) * H,
            (item.x + item.width / 2) * W, (item.y + item.height / 2) * H)


@pytest.fixture()
def scene(tmp_path: Path):
    assets = [_asset(tmp_path, name) for name in ("a", "b", "c")]
    items = [
        _item("a", 0.20, 0.50, 0.25, 0.70),  # tall leader on the left
        _item("b", 0.55, 0.50, 0.18, 0.30),
        _item("c", 0.82, 0.55, 0.15, 0.25),
    ]
    return assets, items


def test_youtube_projection_is_identity(scene) -> None:
    assets, items = scene
    projection = composition_policy(YOUTUBE_16_9).project(items, assets, [])
    assert projection.items is items


def test_reels_reflow_keeps_aspect_scale_order_and_safety(scene) -> None:
    assets, items = scene
    out = composition_policy(LEGACY_REFLOW).project(items, assets, [])
    assert [row.asset_id for row in out.items] == ["a", "b", "c"]
    by_id = {row.asset_id: row for row in out.items}
    scales = []
    for source in items:
        moved = by_id[source.asset_id]
        assert moved.placement_source == REFLOW_PLACEMENT_SOURCE
        assert moved.z == source.z
        # Pixel aspect is preserved exactly (no stretching).
        src_aspect = (source.width * 1920) / (source.height * 1080)
        new_aspect = (moved.width * W) / (moved.height * H)
        assert new_aspect == pytest.approx(src_aspect, rel=1e-9)
        scales.append(moved.width * W / (source.width * 1920))
        x0, y0, x1, y1 = _px_box(moved)
        assert x0 >= REELS_ART_REGION.left * W - 1e-6 and x1 <= REELS_ART_REGION.right * W + 1e-6
        assert y0 >= REELS_ART_REGION.top * H - 1e-6 and y1 <= REELS_ART_REGION.bottom * H + 1e-6
    # One uniform scale preserves the authored size hierarchy (and the leader).
    assert max(scales) - min(scales) < 1e-9
    assert 0.3 < scales[0] <= 1.0
    # Real portrait use: the scene spans more than one row.
    assert len({round(by_id[k].y, 3) for k in by_id}) >= 2
    boxes = [_px_box(row) for row in out.items]
    for i, left in enumerate(boxes):
        for right in boxes[i + 1:]:
            gap = max(right[0] - left[2], left[0] - right[2], right[1] - left[3], left[1] - right[3])
            assert gap >= 64.0 - 1e-6  # no touching, visible spacing


def test_reflow_is_deterministic(scene) -> None:
    assets, items = scene
    policy = composition_policy(LEGACY_REFLOW)
    assert policy.project(items, assets, []).items == policy.project(list(items), assets, []).items


def test_relation_topology_orders_source_before_target(scene) -> None:
    assets, items = scene
    out = composition_policy(LEGACY_REFLOW).project(items, assets, [_relation("c", "a")])
    by_id = {row.asset_id: row for row in out.items}
    # The authored source is never placed below its target in the portrait stack.
    assert by_id["c"].y <= by_id["a"].y + 1e-9


def test_pass2_family_and_contact_cluster_move_rigidly(tmp_path: Path) -> None:
    assets = [
        _asset(tmp_path, "p", family="fam"),
        _asset(tmp_path, "p:secondary-01", family="fam"),
        _asset(tmp_path, "hand"),  # overlaps the family -> authored contact
        _asset(tmp_path, "far"),
    ]
    items = [
        _item("p", 0.30, 0.50, 0.20, 0.50),
        _item("p:secondary-01", 0.38, 0.45, 0.10, 0.15),
        _item("hand", 0.43, 0.60, 0.10, 0.12),
        _item("far", 0.80, 0.50, 0.15, 0.30),
    ]
    out = {row.asset_id: row for row in composition_policy(LEGACY_REFLOW).project(items, assets, []).items}
    ref = {row.asset_id: row for row in items}

    def offset(a: str, b: str, src: dict) -> tuple[float, float]:
        frame = (W, H) if src is out else (1920, 1080)
        return ((src[b].x - src[a].x) * frame[0], (src[b].y - src[a].y) * frame[1])

    s = out["p"].width * W / (ref["p"].width * 1920)
    for other in ("p:secondary-01", "hand"):
        ox, oy = offset("p", other, out)
        rx, ry = offset("p", other, ref)
        assert ox == pytest.approx(rx * s, abs=1e-6) and oy == pytest.approx(ry * s, abs=1e-6)


def test_composition_planner_projects_on_the_active_target(scene) -> None:
    from app.models import StoryBeat

    assets, _ = scene
    for asset, (x0, y0, x1, y1) in zip(assets, ((0, 0, 50, 140), (100, 40, 140, 100), (160, 50, 190, 100))):
        asset.source_bbox = (x0, y0, x1 - x0, y1 - y0)
        asset.source_canvas_width, asset.source_canvas_height = 200, 150
    beat = StoryBeat(id="b1", scene_id="s1", start=0.0, end=2.0, narration="x", action="REVEAL",
                     primary_asset_ids=["a"], support_asset_ids=["b", "c"])
    planner = CompositionPlanner()
    youtube = planner.plan([beat], assets)
    with visual_target(LEGACY_REFLOW):
        reels = planner.plan([beat], assets)
    assert {i.asset_id for i in youtube[0].items} == {i.asset_id for i in reels[0].items}
    assert all(i.placement_source == "authored_scene_geometry" for i in youtube[0].items)
    assert all(i.placement_source == REFLOW_PLACEMENT_SOURCE for i in reels[0].items)
    assert "REELS_9_16" in planner.target_evidence["s1"]
