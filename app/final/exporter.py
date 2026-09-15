from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from app.shared.errors import DependencyUnavailableError, StageFailedError


class FinalExporter:
    def __init__(self, ffmpeg_bin: str = "ffmpeg") -> None:
        self.ffmpeg_bin = ffmpeg_bin

    def mux(self, rendered_video: Path, audio: Path, output: Path) -> Path:
        output.parent.mkdir(parents=True, exist_ok=True)
        command = [
            self.ffmpeg_bin, "-y",
            "-i", str(rendered_video),
            "-i", str(audio),
            "-map", "0:v:0", "-map", "1:a:0",
            "-c:v", "copy",
            "-c:a", "aac", "-b:a", "192k",
            "-shortest",
            "-movflags", "+faststart",
            str(output),
        ]
        try:
            subprocess.run(command, check=True, capture_output=True, text=True)
        except FileNotFoundError as exc:
            raise DependencyUnavailableError("ffmpeg is not available") from exc
        except subprocess.CalledProcessError as exc:
            raise StageFailedError("final mux failed", details={"stderr": exc.stderr[-4000:]}) from exc
        return output

    @staticmethod
    def promote_existing(rendered_video: Path, output: Path) -> Path:
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(rendered_video, output)
        return output
