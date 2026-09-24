from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from app.shared.process import run_hidden


@dataclass(frozen=True, slots=True)
class RenderedVisualReport:
    contact_sheet: Path | None
    sampled: bool


class RenderedVisualQA:
    """Generate lightweight post-render visual evidence without re-encoding the final."""

    def __init__(self, ffmpeg_bin: str = "ffmpeg") -> None:
        self.ffmpeg_bin = ffmpeg_bin

    def inspect(self, video: Path, diagnostics_dir: Path) -> RenderedVisualReport:
        diagnostics_dir.mkdir(parents=True, exist_ok=True)
        target = diagnostics_dir / "visual-contact-sheet.jpg"
        command = [
            self.ffmpeg_bin, "-y", "-hide_banner", "-loglevel", "error", "-i", str(video),
            "-vf", "fps=1/6,scale=320:-2,tile=5x4:padding=6:margin=6:color=white",
            "-frames:v", "1", str(target),
        ]
        try:
            run_hidden(command, check=True, capture_output=True)
        except (OSError, subprocess.CalledProcessError):
            pass
        if target.is_file():
            return RenderedVisualReport(contact_sheet=target, sampled=True)

        # Very short renders may not provide enough samples for the tile filter to
        # flush a contact sheet. Final visual QA must still leave evidence instead of
        # reporting a false "unsampled" state, so fall back to a single encoded frame.
        fallback = [
            self.ffmpeg_bin,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(video),
            "-frames:v",
            "1",
            "-vf",
            "scale=320:-2",
            str(target),
        ]
        try:
            run_hidden(fallback, check=True, capture_output=True)
        except (OSError, subprocess.CalledProcessError):
            return RenderedVisualReport(contact_sheet=None, sampled=False)
        return RenderedVisualReport(
            contact_sheet=target if target.is_file() else None,
            sampled=target.is_file(),
        )
