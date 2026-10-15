from __future__ import annotations

import stat
import subprocess
import zipfile
from pathlib import Path

from fastapi import HTTPException


def validate_zip(path: Path, *, max_entries: int = 5000, max_unpacked: int = 4 * 1024**3) -> None:
    try:
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            if not entries or len(entries) > max_entries:
                raise ValueError("ZIP has an invalid number of entries")
            total = 0
            names: set[str] = set()
            for item in entries:
                name = item.filename.replace("\\", "/")
                parts = name.split("/")
                segments = parts[:-1] if name.endswith("/") else parts
                if (
                    not name
                    or name.startswith("/")
                    or ":" in name
                    or any(part in ("", ".", "..") for part in segments)
                ):
                    raise ValueError("ZIP contains an unsafe path")
                canonical = name.rstrip("/").casefold()
                if canonical in names:
                    raise ValueError("ZIP contains duplicate paths")
                names.add(canonical)
                if stat.S_ISLNK(item.external_attr >> 16):
                    raise ValueError("ZIP contains a symbolic link")
                total += item.file_size
                if total > max_unpacked or (item.compress_size == 0 and item.file_size > 0):
                    raise ValueError("ZIP exceeds decompression limit")
                if item.compress_size and item.file_size / item.compress_size > 200:
                    raise ValueError("ZIP compression ratio is unsafe")
            if archive.testzip() is not None:
                raise ValueError("ZIP contains corrupt data")
    except (zipfile.BadZipFile, OSError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from exc


def validate_audio(path: Path, ffprobe: str) -> None:
    if path.suffix.lower() not in {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg"}:
        raise HTTPException(422, "Unsupported audio type")
    try:
        result = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-select_streams",
                "a:0",
                "-show_entries",
                "stream=codec_type",
                "-of",
                "default=noprint_wrappers=1",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise HTTPException(422, f"Audio probe failed: {exc}") from exc
    if result.returncode or "codec_type=audio" not in result.stdout:
        raise HTTPException(422, "File has no readable audio stream")
