from __future__ import annotations

import subprocess
import sys
from typing import Any


def hidden_window_kwargs() -> dict[str, Any]:
    """Return subprocess options that suppress child console windows on Windows.

    The desktop application runs under pythonw.exe, but console executables such as
    ffmpeg and ffprobe otherwise create their own transient console windows. Keep
    subprocess behavior unchanged on non-Windows platforms.
    """
    if sys.platform != "win32":
        return {}

    options: dict[str, Any] = {}
    create_no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    if create_no_window:
        options["creationflags"] = create_no_window

    startupinfo_type = getattr(subprocess, "STARTUPINFO", None)
    use_show_window = getattr(subprocess, "STARTF_USESHOWWINDOW", 0)
    if startupinfo_type is not None and use_show_window:
        startupinfo = startupinfo_type()
        startupinfo.dwFlags |= use_show_window
        if hasattr(startupinfo, "wShowWindow"):
            startupinfo.wShowWindow = getattr(subprocess, "SW_HIDE", 0)
        options["startupinfo"] = startupinfo

    return options


def run_hidden(*popenargs: Any, **kwargs: Any) -> subprocess.CompletedProcess[Any]:
    """Run a child process without surfacing a console window in the desktop app."""
    options = hidden_window_kwargs()
    if "creationflags" in options:
        kwargs["creationflags"] = int(kwargs.get("creationflags", 0)) | int(
            options["creationflags"]
        )
    if "startupinfo" in options:
        kwargs.setdefault("startupinfo", options["startupinfo"])
    return subprocess.run(*popenargs, **kwargs)
