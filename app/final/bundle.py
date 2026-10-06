from __future__ import annotations

import json
import os
import re
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.shared.errors import StageFailedError

INCOMPLETE_MARKER = ".hexa-incomplete"
FAILED_MARKER = "FAILED.json"
MANIFEST_NAME = "export.json"
_VERSION = re.compile(r"^v([1-9][0-9]{0,5})(?:\..*)?$")
_WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{n}" for n in range(1, 10)),
    *(f"LPT{n}" for n in range(1, 10)),
}


def export_slug(raw: str | None) -> str:
    """Filesystem-safe, stable bundle identity (uppercase ``A-Z0-9_-``, max 80 chars).

    Separators and anything else become ``_``; traversal fragments such as ``..`` or a
    drive prefix therefore can never survive into a path component.
    """
    text = re.sub(r"[^A-Za-z0-9_-]+", "_", str(raw or "")).strip("._-").upper()
    text = re.sub(r"_+", "_", text)[:80].strip("._-")
    if not text or text in _WINDOWS_RESERVED:
        raise StageFailedError(
            "package identity cannot form a safe export folder name",
            details={"code": "EXPORT_IDENTITY_INVALID", "identity": str(raw)[:200]},
        )
    return text


@dataclass(frozen=True, slots=True)
class ExportRootStatus:
    root: Path
    free_bytes: int


class ExportRoot:
    """The configured production export root; fails closed, never falls back elsewhere."""

    def __init__(self, root: Path, *, min_free_bytes: int) -> None:
        self.configured = Path(root)
        self.min_free_bytes = int(min_free_bytes)

    def validate(self) -> ExportRootStatus:
        root = self.configured.expanduser()
        if not root.is_absolute():
            raise self._unavailable("export root must be an absolute path", root)
        anchor = Path(root.anchor)
        if not anchor.exists():
            raise self._unavailable("export drive is not available", root)
        try:
            root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise self._unavailable("export root cannot be created", root, error=str(exc)) from exc
        if _is_link(root):
            raise self._unavailable("export root must not be a symlink or junction", root)
        resolved = root.resolve()
        probe = resolved / f".hexa-write-probe-{uuid.uuid4().hex}"
        try:
            probe.write_bytes(b"ok")
        except OSError as exc:
            raise self._unavailable("export root is not writable", root, error=str(exc)) from exc
        finally:
            try:
                probe.unlink(missing_ok=True)
            except OSError:
                pass
        free = shutil.disk_usage(resolved).free
        if free < self.min_free_bytes:
            raise StageFailedError(
                "export root has insufficient free space for the dual-format bundle",
                details={
                    "code": "EXPORT_ROOT_INSUFFICIENT_SPACE",
                    "path": str(resolved),
                    "free_bytes": free,
                    "required_bytes": self.min_free_bytes,
                },
            )
        return ExportRootStatus(root=resolved, free_bytes=free)

    @staticmethod
    def _unavailable(message: str, root: Path, **extra: Any) -> StageFailedError:
        return StageFailedError(
            message, details={"code": "EXPORT_ROOT_UNAVAILABLE", "path": str(root), **extra},
        )


@dataclass(frozen=True, slots=True)
class ReservedBundle:
    slug: str
    version: int
    directory: Path

    @property
    def name(self) -> str:
        return f"v{self.version}"

    def output_path(self, suffix: str) -> Path:
        return self.directory / f"{self.slug}_{suffix}.mp4"


class ExportBundleWriter:
    """Race-safe ``<root>/<SLUG>/vN`` reservation, staged publish and failure marking.

    A version is reserved by atomic directory creation (``mkdir`` without ``exist_ok``):
    two jobs can never own the same ``vN``. The reserved directory carries an
    ``.hexa-incomplete`` marker from its first instant, and a bundle is valid only when
    ``export.json`` says ``completed`` and the marker is gone. Version numbers are never
    reused, previous versions are never opened for writing, and a failed bundle is
    renamed ``vN.failed-<id>`` with its diagnostics so it cannot look valid.
    """

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def reserve(self, slug: str) -> ReservedBundle:
        package_dir = self._package_dir(slug)
        package_dir.mkdir(exist_ok=True)
        if _is_link(package_dir):
            raise StageFailedError(
                "export package folder must not be a symlink or junction",
                details={"code": "EXPORT_PATH_UNSAFE", "path": str(package_dir)},
            )
        version = self._next_version(package_dir)
        for _ in range(10_000):
            directory = package_dir / f"v{version}"
            try:
                directory.mkdir()
            except FileExistsError:
                version += 1
                continue
            (directory / INCOMPLETE_MARKER).write_text(
                json.dumps({"state": "RENDERING", "reserved_at": _now()}), encoding="utf-8",
            )
            return ReservedBundle(slug=slug, version=version, directory=directory)
        raise StageFailedError(
            "could not reserve an export version",
            details={"code": "EXPORT_VERSION_RESERVATION_FAILED", "path": str(package_dir)},
        )

    def publish(self, bundle: ReservedBundle, manifest: dict[str, Any]) -> Path:
        """Write the manifest atomically, then clear the incomplete marker (valid bundle)."""
        for row in manifest.get("outputs", {}).values():
            path = bundle.directory / row["filename"]
            if not path.is_file() or path.stat().st_size <= 0:
                raise StageFailedError(
                    "export bundle is missing a rendered output",
                    details={"code": "EXPORT_BUNDLE_INCOMPLETE", "path": str(path)},
                )
        target = bundle.directory / MANIFEST_NAME
        temporary = bundle.directory / f".{MANIFEST_NAME}.{uuid.uuid4().hex}.tmp"
        temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, target)
        (bundle.directory / INCOMPLETE_MARKER).unlink()
        return target

    def fail(self, bundle: ReservedBundle, error: BaseException, *, diagnostics: dict[str, Any]) -> Path:
        """Mark a reserved bundle failed; its number stays consumed and it never looks valid."""
        payload = {
            "state": "FAILED",
            "failed_at": _now(),
            "error_type": type(error).__name__,
            "error": str(error)[:2000],
            "code": getattr(error, "effective_code", None) or getattr(error, "code", None),
            **diagnostics,
        }
        try:
            (bundle.directory / FAILED_MARKER).write_text(
                json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8",
            )
        except OSError:
            pass
        failed = bundle.directory.with_name(f"{bundle.name}.failed-{uuid.uuid4().hex[:8]}")
        try:
            bundle.directory.rename(failed)
        except OSError:
            return bundle.directory
        return failed

    @staticmethod
    def is_complete(directory: Path) -> bool:
        manifest = directory / MANIFEST_NAME
        if (directory / INCOMPLETE_MARKER).exists() or not manifest.is_file():
            return False
        try:
            payload = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        return payload.get("completed") is True and all(
            (directory / row["filename"]).is_file() for row in payload.get("outputs", {}).values()
        )

    def _package_dir(self, slug: str) -> Path:
        if slug != export_slug(slug):
            raise StageFailedError(
                "export slug is not sanitized",
                details={"code": "EXPORT_PATH_UNSAFE", "slug": slug},
            )
        root = self.root.resolve()
        package_dir = root / slug
        if package_dir.resolve(strict=False).parent != root:
            raise StageFailedError(
                "export path escapes the export root",
                details={"code": "EXPORT_PATH_UNSAFE", "path": str(package_dir)},
            )
        return package_dir

    @staticmethod
    def _next_version(package_dir: Path) -> int:
        """First candidate after every consumed number (valid, failed or in progress)."""
        used = [
            int(match.group(1))
            for entry in package_dir.iterdir()
            if (match := _VERSION.match(entry.name))
        ]
        return max(used, default=0) + 1


def _is_link(path: Path) -> bool:
    try:
        if path.is_symlink():
            return True
        is_junction = getattr(os.path, "isjunction", None)
        if is_junction is not None and is_junction(path):
            return True
        # Python 3.11 on Windows: a junction is a reparse point that is not a symlink.
        attributes = getattr(os.lstat(path), "st_file_attributes", 0)
        return bool(attributes & 0x400)  # FILE_ATTRIBUTE_REPARSE_POINT
    except OSError:
        return False


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
