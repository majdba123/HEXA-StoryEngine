"""Launcher/environment integrity: the engine that runs is the checkout that was chosen.

The user's worktree shares the main checkout's venv through a directory junction; that
venv's editable install points at the main checkout. The diagnostic therefore showed the
main checkout's interpreter while the traceback (and code) came from the worktree.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import app
from app.diagnostics.report import BuildReportSession
from app.shared import runtime_integrity
from app.shared.runtime_integrity import (
    SOURCE_ROOT_ENV,
    RuntimeSourceMismatchError,
    require_launch_source,
    runtime_identity,
    source_root,
)


def test_source_root_is_the_imported_app_package_checkout() -> None:
    assert source_root() == Path(app.__file__).resolve().parent.parent
    assert (source_root() / "app" / "pipeline.py").is_file()


def test_launch_from_the_imported_checkout_is_accepted() -> None:
    require_launch_source({SOURCE_ROOT_ENV: str(source_root()) + "\\."})
    require_launch_source({})  # no declaring launcher: nothing to compare


def test_launch_from_another_checkout_is_refused(tmp_path: Path) -> None:
    other = tmp_path / "HEXA-StoryEngine"
    other.mkdir()
    with pytest.raises(RuntimeSourceMismatchError) as error:
        require_launch_source({SOURCE_ROOT_ENV: str(other)})
    assert str(other.resolve()) in str(error.value) and str(source_root()) in str(error.value)


def test_identity_reports_an_editable_install_of_another_checkout(monkeypatch, tmp_path: Path) -> None:
    class Dist:
        @staticmethod
        def read_text(name: str) -> str:
            assert name == "direct_url.json"
            return json.dumps({"dir_info": {"editable": True},
                               "url": (tmp_path / "Other Checkout").resolve().as_uri()})

    monkeypatch.setattr(runtime_integrity.metadata, "distribution", lambda _name: Dist())
    identity = runtime_identity()
    assert identity["source_root"] == str(source_root())
    assert identity["editable_install_root"] == str((tmp_path / "Other Checkout").resolve())
    assert identity["editable_install_matches_source"] is False


def test_diagnostic_report_records_the_runtime_source() -> None:
    runtime = BuildReportSession._runtime_source(object.__new__(BuildReportSession))
    assert set(runtime) == {"source_root", "python_executable_invoked", "python_prefix",
                            "editable_install_root", "editable_install_matches_source"}
    home = str(Path.home())
    assert not any(isinstance(value, str) and value.startswith(home) for value in runtime.values())


def test_windows_launcher_declares_its_checkout() -> None:
    launcher = (source_root() / "HEXA.bat").read_text(encoding="utf-8")
    assert 'set "HEXA_SOURCE_ROOT=%~dp0."' in launcher
    assert launcher.index("HEXA_SOURCE_ROOT") < launcher.index("-m app.desktop.main")
