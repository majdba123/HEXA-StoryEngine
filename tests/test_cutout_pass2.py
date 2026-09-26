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


def test_whole_object_completer_absorbs_enclosed_clock_parts() -> None:
    from app.cutout.pass2.completeness import WholeObjectCompleter

    canvas = Image.new("RGBA", (320, 220), (255, 255, 255, 0))
    draw = ImageDraw.Draw(canvas)
    # Protected parent far away.
    draw.rounded_rectangle((20, 55, 130, 180), radius=15, fill=(20, 100, 220, 255))
    # Detached clock: outer ring is the structural seed, hands/dots are disconnected.
    draw.ellipse((190, 45, 275, 130), outline=(220, 140, 30, 255), width=12)
    draw.line((232, 87, 232, 62), fill=(150, 90, 10, 255), width=6)
    draw.line((232, 87, 252, 99), fill=(150, 90, 10, 255), width=6)
    draw.ellipse((260, 82, 267, 89), fill=(150, 90, 10, 255))
    draw.ellipse((257, 98, 264, 105), fill=(150, 90, 10, 255))
    rgba = np.asarray(canvas)

    seed = np.zeros(rgba.shape[:2], dtype=bool)
    yy, xx = np.ogrid[:220, :320]
    dist = np.sqrt((xx - 232.5) ** 2 + (yy - 87.5) ** 2)
    seed[(dist >= 31) & (dist <= 45) & (rgba[:, :, 3] > 0)] = True
    protected = np.zeros_like(seed)
    protected[55:181, 20:131] = rgba[55:181, 20:131, 3] > 0

    result = WholeObjectCompleter().complete(rgba, seed, protected)

    assert result is not None
    assert result.added_pixels > 0
    # Center hands and both dots must travel with the clock ring.
    assert result.mask[75, 232]
    assert result.mask[99, 250]
    assert result.mask[85, 263]
    assert not np.any(result.mask & protected)


def test_whole_object_completer_absorbs_alarm_rays_but_not_neighbour() -> None:
    from app.cutout.pass2.completeness import WholeObjectCompleter

    canvas = Image.new("RGBA", (360, 240), (255, 255, 255, 0))
    draw = ImageDraw.Draw(canvas)
    # Protected neighbouring object.
    draw.rounded_rectangle((20, 75, 145, 205), radius=18, fill=(25, 95, 210, 255))
    # Siren body.
    draw.rounded_rectangle((225, 95, 275, 165), radius=12, fill=(230, 55, 40, 255))
    draw.rectangle((218, 162, 282, 180), fill=(30, 75, 145, 255))
    # Detached authored rays above the siren.
    for x0, y0, x1, y1 in [
        (250, 82, 250, 64), (232, 84, 224, 68), (268, 84, 276, 68),
        (218, 93, 202, 86), (282, 93, 298, 86),
    ]:
        draw.line((x0, y0, x1, y1), fill=(255, 100, 80, 170), width=5)
    rgba = np.asarray(canvas)
    visible = rgba[:, :, 3] > 0
    seed = visible.copy()
    seed[:, :200] = False
    seed[:90, :] = False  # body only, deliberately excluding rays
    protected = np.zeros_like(seed)
    protected[:, :170] = visible[:, :170]

    result = WholeObjectCompleter().complete(rgba, seed, protected)

    assert result is not None
    assert result.mask[68, 250]
    assert result.mask[87, 207]
    assert not np.any(result.mask & protected)


def test_pass2_general_priority_prefers_animation_sized_object_over_tiny_fragment() -> None:
    from app.cutout.pass2.models import CandidateProposal, ProposalSource

    shape = (240, 420)
    mask = np.zeros(shape, dtype=bool)
    useful = CandidateProposal(
        id="useful",
        bbox=(250, 60, 90, 110),
        center=(295.0, 115.0),
        area_share=0.10,
        stability=5 / 7,
        source=ProposalSource.cv,
        core_mask=mask,
    )
    fragment = CandidateProposal(
        id="fragment",
        bbox=(360, 20, 18, 18),
        center=(369.0, 29.0),
        area_share=0.007,
        stability=5 / 7,
        source=ProposalSource.cv,
        core_mask=mask,
    )

    service = Pass2CutoutService()
    useful_score = service._candidate_priority(useful, shape, [])
    fragment_score = service._candidate_priority(fragment, shape, [])

    assert useful_score > fragment_score


def test_pass2_semantic_priority_is_generic_for_animation_useful_objects() -> None:
    from app.cutout.pass2.semantic import SemanticDetection

    shape = (240, 420)
    service = Pass2CutoutService()
    wallet = SemanticDetection(label="wallet", bbox=(240, 60, 100, 100), confidence=0.80)
    unknown = SemanticDetection(label="abstract blob", bbox=(240, 60, 100, 100), confidence=0.80)

    wallet_score = service._semantic_priority(wallet, shape, [])
    unknown_score = service._semantic_priority(unknown, shape, [])

    assert wallet_score > unknown_score


def test_pass2_extractor_preserves_enclosed_white_interior() -> None:
    from app.cutout.pass2.extractor import Pass1StyleExtractor
    from app.cutout.pass2.models import CandidateProposal, ProposalSource

    canvas = Image.new("RGBA", (300, 180), (255, 255, 255, 0))
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle(
        (15, 35, 115, 145),
        radius=14,
        fill=(30, 105, 220, 255),
    )
    draw.ellipse(
        (180, 40, 270, 130),
        fill=(255, 255, 255, 255),
        outline=(25, 55, 120, 255),
        width=10,
    )
    draw.ellipse((215, 75, 235, 95), fill=(230, 150, 35, 255))
    rgba = np.asarray(canvas)

    yy, xx = np.ogrid[:180, :300]
    dist = np.sqrt((xx - 225.0) ** 2 + (yy - 85.0) ** 2)
    core = (dist >= 35.0) & (dist <= 46.0) & (rgba[:, :, 3] > 0)
    protected = np.zeros(core.shape, dtype=bool)
    protected[35:146, 15:116] = rgba[35:146, 15:116, 3] > 0
    proposal = CandidateProposal(
        id="white-interior-badge",
        bbox=(178, 38, 95, 95),
        center=(225.0, 85.0),
        area_share=0.30,
        stability=1.0,
        source=ProposalSource.cv,
        core_mask=core,
    )

    result = Pass1StyleExtractor().extract(rgba, proposal, protected)

    assert result is not None
    assert result.mask[85, 205]
    assert rgba[85, 205, 0:3].tolist() == [255, 255, 255]
    assert not np.any(result.mask & protected)


def test_whole_object_completer_moves_soft_halo_with_detached_object() -> None:
    from app.cutout.pass2.completeness import WholeObjectCompleter
    from app.cutout.pass2.safety import PartitionSafetyGate

    rgba = np.zeros((180, 320, 4), dtype=np.uint8)
    rgba[45:145, 20:115, :3] = (25, 100, 220)
    rgba[45:145, 20:115, 3] = 255

    yy, xx = np.ogrid[:180, :320]
    distance = np.sqrt((xx - 235.0) ** 2 + (yy - 90.0) ** 2)
    body = distance <= 34.0
    halo = (distance > 34.0) & (distance <= 40.0)
    rgba[body, :3] = (220, 65, 45)
    rgba[body, 3] = 255
    rgba[halo, :3] = (230, 120, 110)
    rgba[halo, 3] = 72

    seed = body.copy()
    protected = np.zeros(seed.shape, dtype=bool)
    protected[45:145, 20:115] = True

    completed = WholeObjectCompleter().complete(rgba, seed, protected)

    assert completed is not None
    assert completed.mask[90, 273]
    assert not np.any(completed.mask & protected)
    assert PartitionSafetyGate().validate(rgba[:, :, 3], [completed.mask])
