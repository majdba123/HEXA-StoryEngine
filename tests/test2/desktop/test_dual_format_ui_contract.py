from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
DESKTOP = ROOT / "app" / "desktop" / "main.py"


def _source() -> str:
    return DESKTOP.read_text(encoding="utf-8")


def test_desktop_source_remains_valid_python() -> None:
    ast.parse(_source())


def test_desktop_uses_production_export_root_not_legacy_save_picker() -> None:
    source = _source()

    assert 'QLabel("مجلد التصدير")' in source
    assert "self.export_root_edit.setReadOnly(True)" in source
    assert "settings.export_root is None" in source
    assert "مجلد الحفظ" not in source
    assert "_browse_output" not in source
    assert "replace(Settings.from_env()" not in source
    assert "output_root=output.resolve()" not in source


def test_desktop_exposes_both_dual_format_outputs() -> None:
    source = _source()

    assert 'QPushButton("توليد YouTube + Reels")' in source
    assert 'QPushButton("فتح YouTube")' in source
    assert 'QPushButton("فتح Reels")' in source
    assert "pipeline.generate_bundle(" in source
    assert "str(bundle.youtube.path)" in source
    assert "str(bundle.reels.path)" in source
    assert "str(bundle.directory)" in source


def test_desktop_result_folder_is_the_versioned_bundle() -> None:
    source = _source()

    assert "self._bundle_path = Path(bundle_path)" in source
    assert "if self._bundle_path and self._bundle_path.exists()" in source
    assert "QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._bundle_path)))" in source
