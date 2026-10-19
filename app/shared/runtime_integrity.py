"""Which source tree is this process really running?

A git worktree may share another checkout's virtual environment (for example through a
directory junction). That environment's editable install then points at the *other*
checkout: ``python -m app...`` from the worktree imports the worktree (the current
directory is first on ``sys.path``), but a console script or a launch from elsewhere
silently imports the other checkout. Diagnostics must record the imported source, and a
launcher that names its source tree must refuse to run a different one.
"""
from __future__ import annotations

import json
import os
import sys
from collections.abc import Mapping
from importlib import metadata
from pathlib import Path
from urllib.parse import unquote, urlparse

import app

SOURCE_ROOT_ENV = "HEXA_SOURCE_ROOT"
DISTRIBUTION = "hexa-story-engine"


class RuntimeSourceMismatchError(RuntimeError):
    """The launcher selected one source tree but Python imported another."""


def source_root() -> Path:
    """The checkout whose ``app`` package this process imported."""
    return Path(app.__file__).resolve().parent.parent


def editable_install_root() -> Path | None:
    """The checkout the environment's editable install points at, if any."""
    try:
        raw = metadata.distribution(DISTRIBUTION).read_text("direct_url.json")
    except metadata.PackageNotFoundError:
        return None
    if not raw:
        return None
    try:
        record = json.loads(raw)
    except ValueError:
        return None
    if not (record.get("dir_info") or {}).get("editable"):
        return None
    parsed = urlparse(str(record.get("url") or ""))
    if parsed.scheme != "file":
        return None
    path = unquote(parsed.path)
    if os.name == "nt" and path.startswith("/") and len(path) > 2 and path[2] == ":":
        path = path[1:]
    return Path(path).resolve()


def runtime_identity() -> dict[str, object]:
    """Facts for diagnostics: imported source, interpreter as invoked, editable target."""
    source = source_root()
    editable = editable_install_root()
    return {
        "source_root": str(source),
        "python_executable_invoked": sys.executable,
        "python_prefix": sys.prefix,
        "editable_install_root": str(editable) if editable is not None else None,
        "editable_install_matches_source": None if editable is None else editable == source,
    }


def require_launch_source(environ: Mapping[str, str] | None = None) -> None:
    """Fail when the launcher's declared source tree is not the imported one."""
    expected = (environ if environ is not None else os.environ).get(SOURCE_ROOT_ENV, "").strip()
    if not expected:
        return
    declared = Path(expected).resolve()
    imported = source_root()
    if declared != imported:
        raise RuntimeSourceMismatchError(
            f"HEXA was launched from {declared} but Python imported the engine from {imported}. "
            "Run HEXA.bat from the checkout you want to use, or reinstall its environment."
        )
