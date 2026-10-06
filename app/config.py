from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True, slots=True)
class RenderResourceSettings:
    workers_override: int | None = None
    keep_intermediates: bool = False

    @classmethod
    def from_env(cls) -> "RenderResourceSettings":
        raw = os.getenv("HEXA_RENDER_WORKERS")
        if raw:
            try:
                workers = max(1, min(8, int(raw)))
            except ValueError:
                workers = 1
        else:
            workers = None
        return cls(
            workers_override=workers,
            keep_intermediates=os.getenv("HEXA_KEEP_RENDER_INTERMEDIATES", "0") == "1",
        )


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
    refinement_mode: str = "pass2_vnext"
    alignment_ar_model: str | None = None
    alignment_en_model: str | None = None
    require_forced_alignment: bool = False
    require_text_layer: bool = False
    qwen3_vl_model: str | None = None
    semantic_text_model: str | None = None
    require_semantic_model: bool = False
    render_resources: RenderResourceSettings = field(default_factory=RenderResourceSettings.from_env)

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
            # Pass2 vNext is the production default. It is geometry-preserving and package
            # generic; callers can explicitly opt back to legacy/pass1 for diagnostics.
            refinement_mode=os.getenv("HEXA_REFINEMENT_MODE", "pass2_vnext").strip().lower(),
            alignment_ar_model=os.getenv("HEXA_ALIGNMENT_AR_MODEL") or None,
            alignment_en_model=os.getenv("HEXA_ALIGNMENT_EN_MODEL") or None,
            # Product runs fail closed on missing/unsafe alignment. Tests or controlled
            # offline fallbacks can opt out explicitly through Settings.
            require_forced_alignment=os.getenv("HEXA_REQUIRE_FORCED_ALIGNMENT", "1") == "1",
            # Text overlays are an optional authoring layer. A valid sparse-text
            # decision (including zero cues) must not block video generation unless the
            # operator explicitly opts into a mandatory text workflow.
            require_text_layer=os.getenv("HEXA_REQUIRE_TEXT_LAYER", "0") == "1",
            qwen3_vl_model=os.getenv("HEXA_QWEN3_VL_MODEL") or None,
            semantic_text_model=(
                os.getenv("HEXA_SEMANTIC_TEXT_MODEL", "intfloat/multilingual-e5-small").strip()
                or None
            ),
            # Production must not silently downgrade semantic phrase matching to
            # lexical-only timing when the multilingual encoder is unavailable.
            require_semantic_model=os.getenv("HEXA_REQUIRE_SEMANTIC_MODEL", "1") == "1",
            render_resources=RenderResourceSettings.from_env(),
        )
