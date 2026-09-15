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


def test_large_distant_visuals_are_separated_conservatively(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("HEXA_FLORENCE_MODEL", raising=False)
    monkeypatch.delenv("HEXA_SAM2_CHECKPOINT", raising=False)

    source = tmp_path / "scene.png"
    image = Image.new("RGB", (1000, 560), "white")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((70, 90, 330, 500), radius=45, fill=(30, 80, 180))
    draw.rounded_rectangle((590, 100, 930, 470), radius=55, fill=(180, 80, 25))
    image.save(source)

    package = _package(tmp_path, source, "pkg-test")
    detections = VisionService().analyze(package)
    assert len(detections) == 2

    assets = CutoutService().extract(package, detections, tmp_path / "work")
    assert len(assets) == 2
    assert all(asset.extraction_method == "white_background_group" for asset in assets)
    assert all(asset.source_canvas_width == 1000 for asset in assets)
    assert all(asset.source_canvas_height == 560 for asset in assets)


def test_small_cues_do_not_shred_authored_scene(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("HEXA_FLORENCE_MODEL", raising=False)
    source = tmp_path / "scene-cues.png"
    image = Image.new("RGB", (1200, 600), "white")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((100, 100, 430, 520), radius=55, fill=(20, 80, 180))
    draw.rounded_rectangle((720, 110, 1110, 500), radius=55, fill=(180, 80, 25))
    draw.ellipse((570, 70, 620, 120), fill=(235, 40, 30))
    image.save(source)

    detections = VisionService().analyze(_package(tmp_path, source, "pkg-cues"))
    assert len(detections) == 2


def test_nearby_details_remain_one_visual_group(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("HEXA_FLORENCE_MODEL", raising=False)
    source = tmp_path / "scene-near.png"
    image = Image.new("RGB", (1000, 560), "white")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((250, 130, 600, 470), radius=45, fill=(180, 80, 25))
    draw.ellipse((625, 230, 700, 305), fill=(30, 120, 230))
    image.save(source)

    detections = VisionService().analyze(_package(tmp_path, source, "pkg-near"))
    assert len(detections) == 1
