from pathlib import Path

from PIL import Image, ImageDraw

from app.cutout import CutoutService
from app.models import PackageModel, SceneSource
from app.vision.service import VisionService


def test_scene_image_discovers_and_extracts_individual_visuals(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("HEXA_FLORENCE_MODEL", raising=False)
    monkeypatch.delenv("HEXA_SAM2_CHECKPOINT", raising=False)

    source = tmp_path / "scene.png"
    image = Image.new("RGB", (640, 360), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((60, 80, 210, 270), fill=(30, 30, 30))
    draw.ellipse((410, 95, 560, 245), fill=(220, 50, 50))
    image.save(source)

    package = PackageModel(
        root=tmp_path,
        package_id="pkg-test",
        scenes=[SceneSource(id="scene-001", image_path=source, order=0)],
        script="test",
        manifest={},
    )

    detections = VisionService().analyze(package)
    assert len(detections) >= 2

    assets = CutoutService().extract(package, detections, tmp_path / "work")
    assert len(assets) >= 2
    assert all(asset.extraction_method in {"component_mask", "white_background"} for asset in assets)

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
    draw.polygon([(360, 220), (500, 220), (500, 170), (590, 250), (500, 330), (500, 280), (360, 280)], fill=(0, 120, 255))
    image.save(source)
    package = PackageModel(
        root=tmp_path,
        package_id="pkg-arrow",
        scenes=[SceneSource(id="scene-001", image_path=source, order=0)],
    )

    detections = VisionService().analyze(package)
    assert len(detections) == 3
    widths = sorted(row.bbox[2] for row in detections if row.bbox)
    assert widths[0] < widths[-1]


def test_compound_outline_keeps_enclosed_content_together(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("HEXA_FLORENCE_MODEL", raising=False)
    source = tmp_path / "scene-bubble.png"
    image = Image.new("RGB", (800, 500), "white")
    draw = ImageDraw.Draw(image)
    draw.ellipse((80, 60, 500, 400), outline=(20, 100, 220), width=12)
    draw.rounded_rectangle((190, 170, 390, 300), radius=30, fill=(150, 70, 20))
    draw.ellipse((540, 80, 740, 420), fill=(20, 80, 180))
    image.save(source)
    package = PackageModel(
        root=tmp_path,
        package_id="pkg-bubble",
        scenes=[SceneSource(id="scene-001", image_path=source, order=0)],
    )

    detections = VisionService().analyze(package)
    assert len(detections) == 2
    assert any(row.compound and row.component_count >= 2 for row in detections)
