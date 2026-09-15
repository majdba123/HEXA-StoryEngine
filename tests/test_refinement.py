from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from app.models import VisualAsset
from app.refinement import RefinementService


def _asset(path: Path, *, width: int, height: int) -> VisualAsset:
    return VisualAsset(
        id="scene-001:asset-01",
        scene_id="scene-001",
        role="object",
        image_path=path,
        source_bbox=(100, 80, width, height),
        source_canvas_width=1200,
        source_canvas_height=700,
        source_area_ratio=(width * height) / (1200 * 700),
        extraction_method="component_mask",
    )


def test_refinement_is_noop_for_single_compound_visual(tmp_path: Path) -> None:
    source = tmp_path / "compound.png"
    image = Image.new("RGBA", (500, 300), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((70, 50, 430, 250), radius=50, fill=(30, 90, 210, 255))
    draw.ellipse((170, 90, 300, 220), fill=(220, 180, 40, 255))
    image.save(source)
    parent = _asset(source, width=500, height=300)

    output = RefinementService().refine([parent], tmp_path / "work")
    assert output == [parent]


def test_refinement_splits_only_large_far_secondary_visual(tmp_path: Path) -> None:
    source = tmp_path / "isolated.png"
    image = Image.new("RGBA", (800, 400), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((40, 55, 460, 345), radius=50, fill=(40, 110, 220, 255))
    draw.rounded_rectangle((625, 55, 765, 355), radius=45, fill=(20, 70, 160, 255))
    image.save(source)
    parent = _asset(source, width=800, height=400)

    output = RefinementService().refine([parent], tmp_path / "work")
    assert len(output) == 2
    assert [item.id for item in output] == [
        "scene-001:asset-01",
        "scene-001:asset-01:secondary-01",
    ]
    assert output[0].source_bbox == parent.source_bbox
    assert output[1].source_bbox == parent.source_bbox

    parent_rgba = np.asarray(Image.open(source).convert("RGBA"))
    main_rgba = np.asarray(Image.open(output[0].image_path).convert("RGBA"))
    secondary_rgba = np.asarray(Image.open(output[1].image_path).convert("RGBA"))
    assert np.array_equal(np.maximum(main_rgba[:, :, 3], secondary_rgba[:, :, 3]), parent_rgba[:, :, 3])
    assert not np.any((main_rgba[:, :, 3] > 0) & (secondary_rgba[:, :, 3] > 0))


def test_refinement_keeps_small_isolated_motion_cue_attached(tmp_path: Path) -> None:
    source = tmp_path / "arrow.png"
    image = Image.new("RGBA", (800, 400), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((80, 45, 650, 355), radius=60, fill=(30, 90, 200, 255))
    draw.polygon(
        [(710, 185), (755, 185), (755, 165), (790, 200), (755, 235), (755, 215), (710, 215)],
        fill=(0, 140, 255, 255),
    )
    image.save(source)
    parent = _asset(source, width=800, height=400)

    output = RefinementService().refine([parent], tmp_path / "work")
    assert output == [parent]


def test_refinement_rejects_ambiguous_two_satellites(tmp_path: Path) -> None:
    source = tmp_path / "ambiguous.png"
    image = Image.new("RGBA", (1000, 500), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((330, 60, 670, 440), radius=50, fill=(30, 90, 200, 255))
    draw.rounded_rectangle((30, 70, 180, 430), radius=45, fill=(30, 140, 100, 255))
    draw.rounded_rectangle((820, 70, 970, 430), radius=45, fill=(180, 80, 40, 255))
    image.save(source)
    parent = _asset(source, width=1000, height=500)

    output = RefinementService().refine([parent], tmp_path / "work")
    assert output == [parent]


def test_refinement_never_splits_small_fragments(tmp_path: Path) -> None:
    source = tmp_path / "many-small.png"
    image = Image.new("RGBA", (1000, 500), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rectangle((40, 60, 650, 440), fill=(40, 100, 200, 255))
    for x in range(720, 970, 45):
        draw.ellipse((x, 180, x + 20, 200), fill=(220, 70, 40, 255))
    image.save(source)
    parent = _asset(source, width=1000, height=500)

    output = RefinementService().refine([parent], tmp_path / "work")
    assert output == [parent]
