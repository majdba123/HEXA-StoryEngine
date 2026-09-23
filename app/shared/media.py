from __future__ import annotations

import json
import subprocess
from pathlib import Path

from app.shared.errors import DependencyUnavailableError, StageFailedError
from app.shared.process import run_hidden


def probe_duration(path: Path, ffprobe_bin: str = "ffprobe") -> float:
    command = [
        ffprobe_bin,
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "json",
        str(path),
    ]
    try:
        result = run_hidden(command, check=True, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise DependencyUnavailableError("ffprobe is not available") from exc
    except subprocess.CalledProcessError as exc:
        raise StageFailedError("ffprobe failed", details={"stderr": exc.stderr[-2000:]}) from exc
    payload = json.loads(result.stdout)
    duration = float(payload["format"]["duration"])
    if duration <= 0:
        raise StageFailedError("media duration is invalid")
    return duration
