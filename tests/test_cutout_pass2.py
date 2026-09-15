from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from app.models import VisualAsset
from app.cutout.pass2 import Pass2CutoutService


def _asset(path: Path, *, touching: bool = False) -> VisualAsset:
    canvas = Image.new("RGBA", (420, 240), (255, 255, 255, 0))
    draw = ImageDraw.Draw(canvas)
    # dominant blue object
    draw.rounded_rectangle((30, 50, 230, 200), radius=18, fill=(20, 100, 220, 255), outline=(0, 30, 90, 255), width=5)
    # detached character-like green object with a small real gap
    x0 = 238 if touching else 246
    draw.ellipse((x0 + 18, 40, x0 + 78, 100), fill=(20, 150, 80, 255), outline=(0, 60, 30, 255), width=4)
    draw.rounded_rectangle((x0, 98, x0 + 100, 210), radius=18, fill=(30, 170, 90, 255), outline=(0, 60, 30, 255), width=4)
    if touching:
        draw.rectangle((225, 125, x0 + 10, 145), fill=(0, 60, 30, 255))
    canvas.save(path)
    return VisualAsset(
        id="scene:asset-01",
        scene_id="scene",
        role="primary_visual",
        image_path=path,
        source_bbox=(100, 50, 420, 240),
        confidence=0.9,
        extraction_method="component_mask",
        independent=True,
        compound=True,
        component_count=2,
        source_area_ratio=0.5,
        source_canvas_width=1000,
        source_canvas_height=600,
        can_animate_independently=True,
    )


def _tight_gap_asset(path: Path) -> VisualAsset:
    canvas = Image.new("RGBA", (420, 240), (255, 255, 255, 0))
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle((30, 50, 230, 200), radius=18, fill=(20, 100, 220, 255), outline=(0, 30, 90, 255), width=5)
    # Detached object with a very tight but real gap.
    x0 = 236
    draw.ellipse((x0 + 18, 40, x0 + 78, 100), fill=(20, 150, 80, 255), outline=(0, 60, 30, 255), width=4)
    draw.rounded_rectangle((x0, 98, x0 + 100, 210), radius=18, fill=(30, 170, 90, 255), outline=(0, 60, 30, 255), width=4)
    canvas.save(path)
    return VisualAsset(
        id="scene:asset-tight-gap",
        scene_id="scene",
        role="primary_visual",
        image_path=path,
        source_bbox=(100, 50, 420, 240),
        confidence=0.9,
        extraction_method="component_mask",
        independent=True,
        compound=True,
        component_count=2,
        source_area_ratio=0.5,
        source_canvas_width=1000,
        source_canvas_height=600,
        can_animate_independently=True,
    )


def test_pass2_recovers_tight_real_gap_without_cutting_geometry(tmp_path: Path) -> None:
    parent = _tight_gap_asset(tmp_path / "tight-gap.png")
    result = Pass2CutoutService().refine([parent], tmp_path / "work-tight")
    assert len(result) >= 2
    original = np.asarray(Image.open(parent.image_path).convert("RGBA"))[:, :, 3]
    main = np.asarray(Image.open(result[0].image_path).convert("RGBA"))[:, :, 3]
    reconstructed = main.copy()
    separated_pixels = 0
    for secondary in result[1:]:
        alpha = np.asarray(Image.open(secondary.image_path).convert("RGBA"))[:, :, 3]
        reconstructed = np.maximum(reconstructed, alpha)
        separated_pixels += int(np.count_nonzero(alpha))
    assert separated_pixels > 0
    assert np.array_equal(reconstructed, original)


def test_pass2_preserves_geometry_and_exact_alpha(tmp_path: Path) -> None:
    parent = _asset(tmp_path / "parent.png", touching=False)
    result = Pass2CutoutService().refine([parent], tmp_path / "work")
    assert len(result) >= 2
    assert result[0].source_bbox == parent.source_bbox
    assert result[0].source_canvas_width == parent.source_canvas_width
    assert result[0].source_canvas_height == parent.source_canvas_height
    for secondary in result[1:]:
        assert secondary.source_bbox == parent.source_bbox
        assert secondary.source_canvas_width == parent.source_canvas_width
        assert secondary.source_canvas_height == parent.source_canvas_height

    original = np.asarray(Image.open(parent.image_path).convert("RGBA"))[:, :, 3]
    main = np.asarray(Image.open(result[0].image_path).convert("RGBA"))[:, :, 3]
    reconstructed = main.copy()
    for secondary in result[1:]:
        alpha = np.asarray(Image.open(secondary.image_path).convert("RGBA"))[:, :, 3]
        assert not np.any((main > 0) & (alpha > 0))
        reconstructed = np.maximum(reconstructed, alpha)
    assert np.array_equal(reconstructed, original)


def test_pass2_rejects_hard_touching_objects(tmp_path: Path) -> None:
    parent = _asset(tmp_path / "touching.png", touching=True)
    result = Pass2CutoutService().refine([parent], tmp_path / "work")
    assert len(result) == 1
    assert result[0].image_path == parent.image_path

class _FakeSemantic:
    def __init__(self, bbox: tuple[int, int, int, int]) -> None:
        self.bbox = bbox

    def detect(self, image_path: Path):
        from app.cutout.pass2.semantic import SemanticDetection

        return [SemanticDetection(label="person", bbox=self.bbox, confidence=0.95)]


class _FakeMask:
    def __init__(self, mask: np.ndarray) -> None:
        self.mask = mask

    def segment(self, image_path: Path, bbox: tuple[int, int, int, int]):
        return self.mask.copy()


def test_semantic_backend_can_rescue_complete_detached_character(tmp_path: Path) -> None:
    parent = _asset(tmp_path / "semantic-parent.png", touching=False)
    rgba = np.asarray(Image.open(parent.image_path).convert("RGBA"))
    # full right-hand figure mask from the synthetic scene, preserving parent canvas
    mask = np.zeros(rgba.shape[:2], dtype=bool)
    mask[:, 240:] = rgba[:, 240:, 3] > 0
    service = Pass2CutoutService(
        semantic_backend=_FakeSemantic((240, 30, 115, 190)),
        mask_backend=_FakeMask(mask),
    )
    result = service.refine(
        [parent],
        tmp_path / "work-semantic",
        scene_unit_types={"scene": ["GROUP", "SECONDARY_CHARACTER"]},
    )
    assert len(result) == 2
    assert result[1].source_bbox == parent.source_bbox
    assert result[1].source_canvas_width == parent.source_canvas_width
    assert result[1].source_canvas_height == parent.source_canvas_height
