from pathlib import Path

from PIL import Image, ImageDraw

from app.cutout.service import CutoutService
from app.models import PackageModel, SceneSource
from app.vision.service import VisionService


def _package(tmp_path: Path, source: Path, package_id: str) -> PackageModel:
    return PackageModel(
        root=tmp_path,
        package_id=package_id,
        scenes=[SceneSource(id="scene-001", image_path=source, order=0)],
        script="test",
        manifest={},
    )


def test_scene_image_discovers_and_extracts_individual_visuals(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("HEXA_FLORENCE_MODEL", raising=False)
    monkeypatch.delenv("HEXA_SAM2_CHECKPOINT", raising=False)

    source = tmp_path / "scene.png"
    image = Image.new("RGB", (640, 360), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((60, 80, 210, 270), fill=(30, 30, 30))
    draw.ellipse((410, 95, 560, 245), fill=(220, 50, 50))
    image.save(source)

    package = _package(tmp_path, source, "pkg-test")
    detections = VisionService().analyze(package)
    assert len(detections) == 2

    assets = CutoutService().extract(package, detections, tmp_path / "work")
    assert len(assets) == 2
    assert all(asset.extraction_method in {"component_mask", "white_background"} for asset in assets)
    assert all(asset.independent and not asset.compound for asset in assets)

    first = Image.open(assets[0].image_path).convert("RGBA")
    low, high = first.getchannel("A").getextrema()
    assert low == 0
    assert high == 255


def test_strict_separation_keeps_standalone_arrow_independent(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("HEXA_FLORENCE_MODEL", raising=False)
    source = tmp_path / "scene-arrow.png"
    image = Image.new("RGB", (900, 500), "white")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((40, 80, 250, 430), radius=40, fill=(20, 80, 180))
    draw.rounded_rectangle((620, 110, 860, 420), radius=40, fill=(70, 70, 70))
    draw.polygon(
        [(360, 220), (500, 220), (500, 170), (590, 250), (500, 330), (500, 280), (360, 280)],
        fill=(0, 120, 255),
    )
    image.save(source)

    detections = VisionService().analyze(_package(tmp_path, source, "pkg-arrow"))
    assert len(detections) == 3
    centers = sorted((row.bbox[0] + row.bbox[2] / 2) for row in detections if row.bbox)
    assert centers[0] < centers[1] < centers[2]
    assert all(not row.compound and row.component_count == 1 for row in detections)


def test_nested_but_disconnected_visuals_remain_separate(tmp_path: Path, monkeypatch) -> None:
    """Containment/proximity must never merge physically disconnected islands."""
    monkeypatch.delenv("HEXA_FLORENCE_MODEL", raising=False)
    monkeypatch.delenv("HEXA_SAM2_CHECKPOINT", raising=False)
    source = tmp_path / "scene-bubble.png"
    image = Image.new("RGB", (800, 500), "white")
    draw = ImageDraw.Draw(image)
    draw.ellipse((80, 60, 500, 400), outline=(20, 100, 220), width=12)
    draw.rounded_rectangle((190, 170, 390, 300), radius=30, fill=(150, 70, 20))
    draw.ellipse((560, 90, 740, 420), fill=(20, 80, 180))
    image.save(source)

    package = _package(tmp_path, source, "pkg-bubble")
    detections = VisionService().analyze(package)
    assert len(detections) == 3
    assert all(not row.compound and row.component_count == 1 for row in detections)

    assets = CutoutService().extract(package, detections, tmp_path / "work")
    bubble_detection = next(row for row in detections if row.bbox and row.bbox[0] < 100)
    bubble_index = detections.index(bubble_detection)
    bubble = Image.open(assets[bubble_index].image_path).convert("RGBA")
    # The inner brown object must not be baked into the bubble matte.
    # Its location falls near the center of the bubble crop and must remain transparent.
    center_alpha = bubble.getchannel("A").getpixel((bubble.width // 2, bubble.height // 2))
    assert center_alpha < 32


def test_far_character_and_small_motion_cues_are_not_grouped(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("HEXA_FLORENCE_MODEL", raising=False)
    source = tmp_path / "scene-cues.png"
    image = Image.new("RGB", (1200, 600), "white")
    draw = ImageDraw.Draw(image)
    # Main illustration cluster.
    draw.rounded_rectangle((360, 170, 720, 500), radius=45, fill=(180, 80, 25))
    # Far character.
    draw.rounded_rectangle((950, 100, 1120, 520), radius=55, fill=(20, 80, 180))
    # Standalone arrow and warning lamp.
    draw.polygon([(120, 270), (230, 270), (230, 220), (320, 300), (230, 380), (230, 330), (120, 330)], fill=(0, 120, 255))
    draw.ellipse((790, 80, 860, 150), fill=(235, 40, 30))
    image.save(source)

    detections = VisionService().analyze(_package(tmp_path, source, "pkg-cues"))
    assert len(detections) == 4
    assert all(row.component_count == 1 and not row.compound for row in detections)
