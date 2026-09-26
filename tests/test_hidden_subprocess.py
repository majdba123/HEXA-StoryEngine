from __future__ import annotations

import ast
from pathlib import Path

from app.shared import process


def test_hidden_window_kwargs_are_noop_off_windows(monkeypatch) -> None:
    monkeypatch.setattr(process.sys, "platform", "linux")

    assert process.hidden_window_kwargs() == {}


def test_run_hidden_applies_windows_console_suppression(monkeypatch) -> None:
    class FakeStartupInfo:
        def __init__(self) -> None:
            self.dwFlags = 0
            self.wShowWindow = None

    captured: dict[str, object] = {}

    def fake_run(*args, **kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(process.sys, "platform", "win32")
    monkeypatch.setattr(process.subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    monkeypatch.setattr(process.subprocess, "STARTUPINFO", FakeStartupInfo, raising=False)
    monkeypatch.setattr(process.subprocess, "STARTF_USESHOWWINDOW", 1, raising=False)
    monkeypatch.setattr(process.subprocess, "SW_HIDE", 0, raising=False)
    monkeypatch.setattr(process.subprocess, "run", fake_run)

    process.run_hidden(["tool"], check=False)

    assert captured["creationflags"] == 0x08000000
    startupinfo = captured["startupinfo"]
    assert isinstance(startupinfo, FakeStartupInfo)
    assert startupinfo.dwFlags & 1
    assert startupinfo.wShowWindow == 0


def test_application_does_not_spawn_raw_console_processes() -> None:
    app_root = Path(__file__).resolve().parents[1] / "app"
    offenders: list[str] = []
    forbidden = {"run", "Popen", "call", "check_call", "check_output"}

    for path in app_root.rglob("*.py"):
        if path == app_root / "shared" / "process.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if (
                isinstance(func, ast.Attribute)
                and isinstance(func.value, ast.Name)
                and func.value.id == "subprocess"
                and func.attr in forbidden
            ):
                offenders.append(f"{path.relative_to(app_root)}:{node.lineno}")

    assert offenders == []
