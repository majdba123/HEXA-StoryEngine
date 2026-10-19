"""Desktop Export UX: the export destination is configuration, validated before any work."""
from __future__ import annotations

import ast
import dataclasses
import json
import string
from pathlib import Path

import pytest

from app.config import Settings
from app.desktop.export_preflight import (NOT_CONFIGURED, export_root_problem,
                                          initialize_windows_export_root)
from app.final.bundle import ExportBundleWriter, _foreign_windows_drive_path

ROOT = Path(__file__).resolve().parents[3]
DESKTOP = ROOT / "app" / "desktop" / "main.py"
E_DRIVE_ROOT = r"E:\HEXA_Exports"


@pytest.fixture
def isolated_env(tmp_path: Path, monkeypatch) -> Path:
    for name in ("HEXA_EXPORT_ROOT", "HEXA_SETTINGS_FILE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HEXA_WORK_ROOT", str(tmp_path / "work"))
    monkeypatch.setenv("HEXA_OUTPUT_ROOT", str(tmp_path / "out"))
    return tmp_path


def _settings_file(tmp_path: Path, monkeypatch, export_root: str) -> None:
    path = tmp_path / "hexa.settings.json"
    path.write_text(json.dumps({"export_root": export_root}), encoding="utf-8")
    monkeypatch.setenv("HEXA_SETTINGS_FILE", str(path))


# GUI ----------------------------------------------------------------------------------------
def test_gui_needs_only_package_and_audio() -> None:
    source = DESKTOP.read_text(encoding="utf-8")
    tree = ast.parse(source)
    window = next(n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == "MainWindow")
    init = next(n for n in window.body if isinstance(n, ast.FunctionDef) and n.name == "__init__")
    line_edits = [n for n in ast.walk(init) if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "QLineEdit"]
    assert len(line_edits) == 2  # package + audio only
    for removed in ('QLabel("مجلد التصدير")', 'QPushButton("فتح")', "_export_root_row",
                    "_open_export_root", "_refresh_export_root", "open_export_root_button"):
        assert removed not in source
    assert 'QPushButton("فتح مجلد النتيجة")' in source  # bundle-folder button retained
    assert "QFileDialog.getExistingDirectory(self, \"اختر مجلد Final Package\")" in source
    start = source.index("def _start_generation")
    assert source.index("export_root_problem(settings)", start) < source.index("GenerationWorker(", start)


# Configuration --------------------------------------------------------------------------------
def test_configured_e_drive_destination_is_used(isolated_env: Path, monkeypatch) -> None:
    _settings_file(isolated_env, monkeypatch, E_DRIVE_ROOT)
    assert Settings.from_env().export_root == Path(E_DRIVE_ROOT)


def test_environment_override_keeps_precedence(isolated_env: Path, monkeypatch) -> None:
    _settings_file(isolated_env, monkeypatch, E_DRIVE_ROOT)
    override = isolated_env / "explicit-exports"
    monkeypatch.setenv("HEXA_EXPORT_ROOT", str(override))
    assert Settings.from_env().export_root == override


def test_no_configuration_means_no_silent_default(isolated_env: Path, monkeypatch) -> None:
    monkeypatch.setenv("HEXA_SETTINGS_FILE", str(isolated_env / "absent.json"))
    settings = Settings.from_env()
    assert settings.export_root is None
    assert export_root_problem(settings) == NOT_CONFIGURED


# Pre-render validation --------------------------------------------------------------------------
def _settings(export_root: Path, **extra) -> Settings:
    base = Settings(work_root=Path("w"), output_root=Path("o"), ffmpeg_bin="ffmpeg", ffprobe_bin="ffprobe",
                    whisper_model="small", engine_host="127.0.0.1", engine_port=1, allow_scene_fallback=False,
                    export_root=export_root)
    return dataclasses.replace(base, **extra)


def test_usable_configured_root_passes(tmp_path: Path) -> None:
    root = tmp_path / "HEXA_Exports"
    assert export_root_problem(_settings(root)) is None
    assert root.is_dir() and not any(root.iterdir())  # created, probe removed, nothing dumped


def test_missing_drive_fails_clearly_without_fallback(tmp_path: Path) -> None:
    letter = next(c for c in reversed(string.ascii_uppercase) if not Path(f"{c}:\\").exists())
    missing = Path(f"{letter}:\\HEXA_Exports")
    message = export_root_problem(_settings(missing))
    assert message is not None and str(missing) in message and "القرص غير موجود" in message
    assert not missing.exists()


def test_windows_drive_configuration_is_foreign_on_posix() -> None:
    assert _foreign_windows_drive_path(Path(r"Z:\HEXA_Exports"), platform="posix")
    assert _foreign_windows_drive_path(Path("Z:/HEXA_Exports"), platform="posix")
    assert not _foreign_windows_drive_path(Path(r"Z:\HEXA_Exports"), platform="nt")
    assert not _foreign_windows_drive_path(Path("/tmp/HEXA_Exports"), platform="posix")


def test_unwritable_root_fails_clearly(tmp_path: Path, monkeypatch) -> None:
    original = Path.write_bytes

    def refuse(self, data):
        if self.name.startswith(".hexa-write-probe-"):
            raise PermissionError("denied")
        return original(self, data)

    monkeypatch.setattr(Path, "write_bytes", refuse)
    message = export_root_problem(_settings(tmp_path / "HEXA_Exports"))
    assert message is not None and "لا توجد صلاحية كتابة" in message


def test_insufficient_space_fails_clearly(tmp_path: Path) -> None:
    message = export_root_problem(_settings(tmp_path / "HEXA_Exports", export_min_free_bytes=1 << 62))
    assert message is not None and "لا توجد مساحة كافية" in message


def test_bundle_layout_and_versioning_unchanged_under_configured_root(tmp_path: Path) -> None:
    root = tmp_path / "HEXA_Exports"
    assert export_root_problem(_settings(root)) is None
    writer = ExportBundleWriter(root)
    first, second = writer.reserve("HEXA_BLACK_HAT_HACKER_AR"), writer.reserve("HEXA_BLACK_HAT_HACKER_AR")
    assert first.directory == root / "HEXA_BLACK_HAT_HACKER_AR" / "v1"
    assert second.directory == root / "HEXA_BLACK_HAT_HACKER_AR" / "v2"
    assert first.output_path("YOUTUBE") == first.directory / "HEXA_BLACK_HAT_HACKER_AR_YOUTUBE.mp4"
    assert sorted(p.name for p in root.iterdir()) == ["HEXA_BLACK_HAT_HACKER_AR"]  # nothing else in the root


# Windows desktop first-run setup ------------------------------------------------------------
def test_windows_desktop_bootstrap_persists_export_on_e_and_passes_preflight(
    tmp_path: Path, monkeypatch,
) -> None:
    local = tmp_path / "hexa.settings.json"
    drive = tmp_path / "mock-drive-e"
    drive.mkdir()
    # This simulates a present E drive on Linux CI without writing to the host's drives.
    local.write_text(json.dumps({"whisper_model": "small", "ui_language": "ar"}), encoding="utf-8")
    monkeypatch.setattr("app.config.LOCAL_SETTINGS_FILE", local)
    monkeypatch.delenv("HEXA_EXPORT_ROOT", raising=False)
    monkeypatch.delenv("HEXA_SETTINGS_FILE", raising=False)
    monkeypatch.setenv("HEXA_WORK_ROOT", str(tmp_path / "work"))
    monkeypatch.setenv("HEXA_OUTPUT_ROOT", str(tmp_path / "out"))

    assert initialize_windows_export_root(platform="nt", drive_root=drive, settings_file=local) is None
    saved = json.loads(local.read_text(encoding="utf-8"))
    assert saved == {"whisper_model": "small", "ui_language": "ar",
                     "export_root": str(drive / "HEXA_Exports")}
    settings = Settings.from_env()
    assert settings.export_root == drive / "HEXA_Exports"
    assert export_root_problem(settings) is None
    assert settings.export_root.is_dir()
    assert initialize_windows_export_root(platform="nt", drive_root=drive,
                                          settings_file=local) is None
    assert json.loads(local.read_text(encoding="utf-8")) == saved
    assert not (tmp_path / "HEXA_Exports").exists()


def test_windows_bootstrap_does_not_override_explicit_paths(tmp_path: Path, monkeypatch) -> None:
    drive = tmp_path / "mock-drive-e"
    drive.mkdir()
    settings_file = tmp_path / "hexa.settings.json"
    chosen = tmp_path / "chosen-destination"
    settings_file.write_text(json.dumps({"export_root": str(chosen), "other": 3}), encoding="utf-8")
    before = settings_file.read_bytes()
    monkeypatch.delenv("HEXA_EXPORT_ROOT", raising=False)
    monkeypatch.delenv("HEXA_SETTINGS_FILE", raising=False)
    assert initialize_windows_export_root(platform="nt", drive_root=drive,
                                          settings_file=settings_file) is None
    assert settings_file.read_bytes() == before
    settings_file.unlink()
    monkeypatch.setenv("HEXA_EXPORT_ROOT", str(chosen))
    assert initialize_windows_export_root(platform="nt", drive_root=drive,
                                          settings_file=settings_file) is None
    assert not settings_file.exists()
    monkeypatch.delenv("HEXA_EXPORT_ROOT")
    monkeypatch.setenv("HEXA_SETTINGS_FILE", str(tmp_path / "operator.json"))
    assert initialize_windows_export_root(platform="nt", drive_root=drive,
                                          settings_file=settings_file) is None
    assert not settings_file.exists()


def test_windows_bootstrap_missing_drive_fails_closed(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("HEXA_EXPORT_ROOT", raising=False)
    monkeypatch.delenv("HEXA_SETTINGS_FILE", raising=False)
    local = tmp_path / "hexa.settings.json"
    message = initialize_windows_export_root(platform="nt", drive_root=tmp_path / "absent-drive-e",
                                             settings_file=local)
    assert message is not None and "قرص E:" in message and "C:" in message
    assert not local.exists()
    assert not (tmp_path / "HEXA_Exports").exists()


def test_desktop_bootstrap_skips_non_windows_and_rejects_corrupt_json(
    tmp_path: Path, monkeypatch,
) -> None:
    monkeypatch.delenv("HEXA_EXPORT_ROOT", raising=False)
    monkeypatch.delenv("HEXA_SETTINGS_FILE", raising=False)
    local = tmp_path / "hexa.settings.json"
    drive = tmp_path / "mock-drive-e"
    drive.mkdir()
    assert initialize_windows_export_root(platform="posix", drive_root=drive,
                                          settings_file=local) is None
    assert not local.exists()
    local.write_text("{not-json", encoding="utf-8")
    before = local.read_bytes()
    error = initialize_windows_export_root(platform="nt", drive_root=drive, settings_file=local)
    assert error is not None and "تعذر قراءة" in error
    assert local.read_bytes() == before


def test_gui_initializes_desktop_export_before_loading_settings() -> None:
    source = DESKTOP.read_text(encoding="utf-8")
    start = source.index("def _start_generation")
    assert source.index("initialize_windows_export_root()", start) < source.index(
        "Settings.from_env()", start)
    assert source.index("Settings.from_env()", start) < source.index(
        "export_root_problem(settings)", start)
