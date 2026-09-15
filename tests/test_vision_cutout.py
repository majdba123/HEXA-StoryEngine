from pathlib import Path

from PIL import Image, ImageDraw

from app.cutout.service import CutoutService
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
    assert all(asset.extraction_method == "white_background" for asset in assets)

    first = Image.open(assets[0].image_path).convert("RGBA")
    low, high = first.getchannel("A").getextrema()
    assert low == 0
    assert high == 255
