from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Settings:
    work_root: Path
    output_root: Path
    ffmpeg_bin: str
    ffprobe_bin: str
    whisper_model: str
    engine_host: str
    engine_port: int
    allow_scene_fallback: bool

    @classmethod
    def from_env(cls) -> "Settings":
        root = Path(os.getenv("HEXA_WORK_ROOT", ".hexa/work")).resolve()
        output = Path(os.getenv("HEXA_OUTPUT_ROOT", ".hexa/outputs")).resolve()
        root.mkdir(parents=True, exist_ok=True)
        output.mkdir(parents=True, exist_ok=True)
        return cls(
            work_root=root,
            output_root=output,
            ffmpeg_bin=os.getenv("HEXA_FFMPEG", "ffmpeg"),
            ffprobe_bin=os.getenv("HEXA_FFPROBE", "ffprobe"),
            whisper_model=os.getenv("HEXA_WHISPER_MODEL", "small"),
            engine_host=os.getenv("HEXA_ENGINE_HOST", "127.0.0.1"),
            engine_port=int(os.getenv("HEXA_ENGINE_PORT", "8765")),
            allow_scene_fallback=os.getenv("HEXA_ALLOW_SCENE_FALLBACK", "0") == "1",
        )
