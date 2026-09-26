from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from app.shared.errors import DependencyUnavailableError, StageFailedError
from app.shared.process import run_hidden


class FinalExporter:
    def __init__(self, ffmpeg_bin: str = "ffmpeg") -> None:
        self.ffmpeg_bin = ffmpeg_bin

    def preflight(self, rendered_video: Path, root: Path) -> Path:
        """Exercise the real copy-video + AAC + MP4 mux path on a tiny probe."""
        root.mkdir(parents=True, exist_ok=True)
        target = root / "ffmpeg-final-preflight.mp4"
        command = [
            self.ffmpeg_bin, "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(rendered_video),
            "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono",
            "-map", "0:v:0", "-map", "1:a:0",
            "-c:v", "copy",
            "-c:a", "aac", "-b:a", "192k",
            "-t", "0.08",
            "-movflags", "+faststart",
            str(target),
        ]
        try:
            run_hidden(command, check=True, capture_output=True, text=True)
        except FileNotFoundError as exc:
            raise DependencyUnavailableError(
                "ffmpeg is not available",
                details={"code": "FFMPEG_UNAVAILABLE", "binary": self.ffmpeg_bin},
            ) from exc
        except subprocess.CalledProcessError as exc:
            raise StageFailedError(
                "final mux preflight failed",
                details={
                    "code": "FINAL_MUX_PREFLIGHT_FAILED",
                    "stderr": exc.stderr[-4000:],
                },
            ) from exc
        if not target.is_file() or target.stat().st_size == 0:
            raise StageFailedError(
                "final mux preflight produced no output",
                details={"code": "FINAL_MUX_PREFLIGHT_EMPTY"},
            )
        return target

    def mux(self, rendered_video: Path, audio: Path, output: Path) -> Path:
        output.parent.mkdir(parents=True, exist_ok=True)
        command = [
            self.ffmpeg_bin, "-y",
            "-i", str(rendered_video),
            "-i", str(audio),
            "-map", "0:v:0", "-map", "1:a:0",
            "-c:v", "copy",
            "-c:a", "aac", "-b:a", "192k",
            # Do not use -shortest here. AAC encoder priming/tail packet semantics can
            # make the muxed audio stream a few milliseconds shorter than a frame-locked
            # video, and -shortest would then drop valid final video frames.
            "-movflags", "+faststart",
            str(output),
        ]
        try:
            run_hidden(command, check=True, capture_output=True, text=True)
        except FileNotFoundError as exc:
            raise DependencyUnavailableError(
                "ffmpeg is not available",
                details={"code": "FFMPEG_UNAVAILABLE", "binary": self.ffmpeg_bin},
            ) from exc
        except subprocess.CalledProcessError as exc:
            raise StageFailedError(
                "final mux failed",
                details={"code": "FINAL_MUX_FAILED", "stderr": exc.stderr[-4000:]},
            ) from exc
        return output

    @staticmethod
    def promote_existing(rendered_video: Path, output: Path) -> Path:
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(rendered_video, output)
        return output
