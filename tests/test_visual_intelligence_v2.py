from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw
import pytest

from app.assets import AssetManager
from app.composition import CompositionPlanner
from app.director import VisualDirector
from app.layout import ConstraintLayoutSolver
from app.models import (
    CompositionBeat,
    LayoutItem,
    MotionCue,
    PackageModel,
    SceneSource,
    StoryBeat,
    TextPlan,
    Transcript,
    TranscriptSegment,
    VisualAsset,
)
from app.motion import ReferenceMotionEnforcer
from app.qa import AuthoringVisualQA
from app.shared.errors import StageFailedError


def _image(path: Path, box: tuple[int, int, int, int] = (10, 10, 40, 40), *, size=(100, 100)) -> None:
    image = Image.new("RGBA", size, (255, 255, 255, 0))
    draw = ImageDraw.Draw(image)
    x, y, w, h = box
    draw.rectangle((x, y, x + w, y + h), fill=(20, 80, 180, 255))
    image.save(path)


def _beat(ids: list[str]) -> StoryBeat:
    return StoryBeat(
        id="beat-001",
        scene_id="scene-001",
        start=0.0,
        end=2.0,
        audio_start=0.2,
        audio_end=1.8,
        narration="الرصيد المتاح",
        primary_asset_ids=ids[:1],
        support_asset_ids=ids[1:],
        action="INTRODUCE",
    )


def test_asset_manager_marks_pass2_family_canvas(tmp_path: Path) -> None:
    path = tmp_path / "secondary.png"
    _image(path)
    asset = VisualAsset(
        id="scene:asset-01:secondary-01",
        scene_id="scene",
        role="secondary_object",
        image_path=path,
        source_bbox=(10, 10, 40, 40),
        source_canvas_width=100,
        source_canvas_height=100,
        extraction_method="component_mask+pass2_secondary",
    )
    normalized = AssetManager.normalize([asset])[0]
    assert normalized.parent_asset_id == "scene:asset-01"
    assert normalized.asset_family_id == "scene:asset-01"
    assert normalized.render_as_family_canvas is True


def test_asset_manager_leaves_tight_pass1_asset_independent(tmp_path: Path) -> None:
    path = tmp_path / "tight.png"
    _image(path, size=(50, 50))
    asset = VisualAsset(
        id="a1", scene_id="s", role="object", image_path=path,
        source_bbox=(10, 10, 40, 40), source_canvas_width=100, source_canvas_height=100,
        extraction_method="component_mask",
    )
    normalized = AssetManager.normalize([asset])[0]
    assert normalized.asset_family_id == "a1"
    assert normalized.render_as_family_canvas is False


def test_composition_preserves_shared_family_registration(tmp_path: Path) -> None:
    main_path = tmp_path / "main.png"
    secondary_path = tmp_path / "secondary.png"
    _image(main_path, (8, 20, 30, 60))
    _image(secondary_path, (62, 25, 24, 35))
    assets = AssetManager.normalize([
        VisualAsset(
            id="a", scene_id="scene-001", role="primary", image_path=main_path,
            source_bbox=(5, 10, 85, 75), source_canvas_width=100, source_canvas_height=100,
            extraction_method="component_mask+pass2_main", asset_family_id="a",
            render_as_family_canvas=True,
        ),
        VisualAsset(
            id="a:secondary-01", scene_id="scene-001", role="secondary_object", image_path=secondary_path,
            source_bbox=(5, 10, 85, 75), source_canvas_width=100, source_canvas_height=100,
            extraction_method="component_mask+pass2_secondary", parent_asset_id="a",
            asset_family_id="a", render_as_family_canvas=True,
        ),
    ])
    result = CompositionPlanner().plan([_beat(["a", "a:secondary-01"])], assets)[0]
    by_id = {item.asset_id: item for item in result.items}
    first, second = by_id["a"], by_id["a:secondary-01"]
    assert (first.x, first.y, first.width, first.height) == pytest.approx(
        (second.x, second.y, second.width, second.height)
    )
    assert first.placement_source.startswith("authored")
    assert second.placement_source.startswith("authored")


def test_layout_solver_preserves_safe_authored_layout(tmp_path: Path) -> None:
    a_path, b_path = tmp_path / "a.png", tmp_path / "b.png"
    _image(a_path)
    _image(b_path)
    assets = [
        VisualAsset(id="a", scene_id="s", role="object", image_path=a_path, extraction_method="test"),
        VisualAsset(id="b", scene_id="s", role="object", image_path=b_path, extraction_method="test"),
    ]
    beat = CompositionBeat(beat_id="b", items=[
        LayoutItem(asset_id="a", x=0.25, y=0.5, width=0.25, height=0.4),
        LayoutItem(asset_id="b", x=0.75, y=0.5, width=0.25, height=0.4),
    ])
    solved = ConstraintLayoutSolver().solve(beat, assets)
    assert solved.items == beat.items
    assert "layout:authored_preserved" in solved.state_evidence


def test_layout_solver_repairs_catastrophic_independent_overlap(tmp_path: Path) -> None:
    a_path, b_path = tmp_path / "a.png", tmp_path / "b.png"
    _image(a_path)
    _image(b_path)
    assets = [
        VisualAsset(id="a", scene_id="s", role="object", image_path=a_path, extraction_method="test"),
        VisualAsset(id="b", scene_id="s", role="object", image_path=b_path, extraction_method="test"),
    ]
    beat = CompositionBeat(beat_id="b", items=[
        LayoutItem(asset_id="a", x=0.50, y=0.5, width=0.50, height=0.6),
        LayoutItem(asset_id="b", x=0.52, y=0.5, width=0.50, height=0.6),
    ])
    solved = ConstraintLayoutSolver().solve(beat, assets)
    assert "layout:constraint_repair" in solved.state_evidence
    assert abs(solved.items[0].x - solved.items[1].x) > 0.30


def test_short_directional_motion_becomes_non_directional() -> None:
    cue = MotionCue(
        beat_id="b", asset_id="a", kind="program_v3", start=0.0, end=0.2,
        params={"program": {"name": "enter", "keyframes": [
            {"progress": 0.0, "dx": -0.2, "dy": 0.0, "scale": 0.95},
            {"progress": 1.0, "dx": 0.0, "dy": 0.0, "scale": 1.0},
        ]}},
    )
    fixed = ReferenceMotionEnforcer().enforce([cue])[0]
    assert fixed.params["reference_motion_adjusted"] is True
    assert all(frame["dx"] == 0.0 and frame["dy"] == 0.0 for frame in fixed.params["program"]["keyframes"])


def test_long_directional_motion_is_preserved() -> None:
    cue = MotionCue(
        beat_id="b", asset_id="a", kind="program_v3", start=0.0, end=0.5,
        params={"program": {"name": "enter", "keyframes": [
            {"progress": 0.0, "dx": -0.2, "dy": 0.0, "scale": 1.0},
            {"progress": 1.0, "dx": 0.0, "dy": 0.0, "scale": 1.0},
        ]}},
    )
    assert ReferenceMotionEnforcer().enforce([cue])[0] == cue


def test_visual_director_never_invents_asset_ids(tmp_path: Path) -> None:
    scene = tmp_path / "scene.png"
    _image(scene)
    package = PackageModel(
        root=tmp_path,
        package_id="p",
        scenes=[SceneSource(id="scene-001", image_path=scene, order=1)],
        script="الرصيد المتاح",
    )
    assets = [VisualAsset(id="a", scene_id="scene-001", role="primary", image_path=scene, extraction_method="test")]
    direction = VisualDirector().plan(package, [_beat(["a"])], assets)[0]
    assert direction.primary_asset_id == "a"
    assert direction.active_asset_ids == ("a",)
    assert "final_package_geometry" in direction.evidence


def test_text_layer_gate_fails_closed_only_when_required() -> None:
    transcript = Transcript(
        language="ar", duration=1.0,
        segments=[TranscriptSegment(start=0.0, end=1.0, text="اختبار")],
        timing_source="forced_alignment",
    )
    report = AuthoringVisualQA().inspect(
        transcript=transcript,
        composition=[], motion=[], text=TextPlan(), assets=[], fps=30,
    )
    with pytest.raises(StageFailedError):
        AuthoringVisualQA.require(report, require_text=True)
    AuthoringVisualQA.require(report, require_text=False)