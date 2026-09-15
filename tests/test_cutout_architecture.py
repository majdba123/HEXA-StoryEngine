from __future__ import annotations

import importlib.util
from pathlib import Path

from app.cutout import CutoutService, Pass2CutoutService
from app.cutout.pass1 import CutoutService as Pass1CutoutService
from app.cutout.pass2 import Pass2CutoutService as Pass2Service


def test_cutout_public_api_points_to_pass_packages() -> None:
    assert CutoutService is Pass1CutoutService
    assert Pass2CutoutService is Pass2Service


def test_deprecated_refinement2_package_is_removed() -> None:
    assert importlib.util.find_spec("app.refinement2") is None


def test_cutout_layout_has_no_old_root_service_modules() -> None:
    cutout_root = Path(__file__).parents[1] / "app" / "cutout"
    assert not (cutout_root / "service.py").exists()
    assert not (cutout_root / "sam2.py").exists()
    assert (cutout_root / "pass1" / "service.py").is_file()
    assert (cutout_root / "pass1" / "sam2.py").is_file()
    assert (cutout_root / "pass2" / "service.py").is_file()


def test_source_contains_no_refinement2_imports() -> None:
    app_root = Path(__file__).parents[1] / "app"
    offenders: list[str] = []
    for path in app_root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "app.refinement2" in text:
            offenders.append(str(path.relative_to(app_root.parent)))
    assert offenders == []
