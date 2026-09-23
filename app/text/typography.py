from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from PIL import ImageFont

from app.models import TextCue


@dataclass(frozen=True, slots=True)
class GlyphMeasurement:
    width: float
    height: float
    method: str


@dataclass(frozen=True, slots=True)
class TypographyProfile:
    """Resolution-independent typography tokens for the 16:9 HEXA canvas."""

    font_family: str = "Noto Kufi Arabic ExtraBold"
    reference_width: int = 1920
    reference_height: int = 1080
    min_size_ratio: float = 112 / 1080
    max_size_ratio: float = 220 / 1080
    outline_ratio: float = 0.052

    @classmethod
    def production(cls) -> "TypographyProfile":
        return cls(
            font_family=(
                os.getenv("HEXA_TEXT_FONT_FAMILY")
                or "Noto Kufi Arabic ExtraBold"
            ).strip()
        )

    def target_size_ratio(self, cue: TextCue) -> float:
        if cue.semantic_type in {"warning_amount", "warning", "amount", "number"}:
            pixels = 188.0
        elif cue.semantic_type == "emphasis" or cue.priority >= 85:
            pixels = 178.0
        else:
            pixels = 158.0

        words = [row for row in cue.text.split() if row]
        length = len(cue.text.strip())
        if cue.priority >= 95:
            pixels += 16.0
        elif cue.priority >= 85:
            pixels += 8.0
        if len(words) == 1 and length <= 10:
            pixels += 12.0
        elif len(words) >= 4:
            pixels -= 18.0
        if length >= 24:
            pixels -= 12.0
        elif length <= 8:
            pixels += 6.0

        ratio = pixels / self.reference_height
        return max(self.min_size_ratio, min(self.max_size_ratio, ratio))

    def size_candidates(self, cue: TextCue) -> tuple[float, ...]:
        target = self.target_size_ratio(cue)
        raw = (
            target,
            target * 0.92,
            target * 0.84,
            target * 0.76,
            target * 0.69,
            self.min_size_ratio,
        )
        output: list[float] = []
        for value in raw:
            value = max(self.min_size_ratio, min(self.max_size_ratio, value))
            if not any(abs(value - previous) < 0.001 for previous in output):
                output.append(value)
        return tuple(output)


class TypographyMetrics:
    """Measure the actual shaped display font when available, with safe fallback.

    Pillow uses libraqm/HarfBuzz when the runtime supports it. The fallback remains
    deliberately conservative so missing local fonts never create unsafe placement.
    """

    _FONT_FILENAMES = (
        "BalooBhaijaan2-ExtraBold.ttf",
        "NotoKufiArabic-ExtraBold.ttf",
        "NotoKufiArabic-Black.ttf",
        "NotoSansArabic-ExtraBold.ttf",
        "NotoSansArabic-Black.ttf",
    )

    def __init__(
        self,
        profile: TypographyProfile | None = None,
        *,
        font_path: Path | None = None,
    ) -> None:
        self.profile = profile or TypographyProfile.production()
        self.font_path = font_path or self._resolve_font_path()
        self._font_cache: dict[int, ImageFont.FreeTypeFont | None] = {}

    def measure(
        self,
        text: str,
        *,
        size_ratio: float,
        outline_ratio: float | None = None,
    ) -> GlyphMeasurement:
        size_px = max(1, round(size_ratio * self.profile.reference_height))
        outline_px = max(
            1,
            round(size_px * (outline_ratio or self.profile.outline_ratio)),
        )
        font = self._font(size_px)
        if font is not None:
            kwargs = {"stroke_width": outline_px}
            try:
                if self._contains_arabic(text):
                    bbox = font.getbbox(text, direction="rtl", language="ar", **kwargs)
                else:
                    bbox = font.getbbox(text, direction="ltr", **kwargs)
                method = "pillow_raqm"
            except (TypeError, ValueError, KeyError):
                bbox = font.getbbox(text, **kwargs)
                method = "pillow"
            width_px = max(1, bbox[2] - bbox[0])
            height_px = max(1, bbox[3] - bbox[1])
            width_px += max(4, round(size_px * 0.035))
            height_px += max(4, round(size_px * 0.035))
            return GlyphMeasurement(
                width=width_px / self.profile.reference_width,
                height=height_px / self.profile.reference_height,
                method=method,
            )

        units = 0.0
        for char in text.strip():
            if char.isspace():
                units += 0.32
            elif char.isdigit():
                units += 0.62
            elif char in ".,:;!?،؛؟-/":
                units += 0.30
            elif "\u0600" <= char <= "\u08ff":
                units += 0.66
            else:
                units += 0.58
        width_px = max(size_px * 1.15, units * size_px + 2 * outline_px)
        height_px = size_px * 1.20 + 2 * outline_px
        return GlyphMeasurement(
            width=min(self.profile.reference_width * 0.72, width_px)
            / self.profile.reference_width,
            height=height_px / self.profile.reference_height,
            method="conservative_fallback",
        )

    def outline_pixels(self, size_ratio: float, *, output_height: int) -> float:
        return max(2.0, output_height * size_ratio * self.profile.outline_ratio)

    def _font(self, size_px: int) -> ImageFont.FreeTypeFont | None:
        if size_px in self._font_cache:
            return self._font_cache[size_px]
        if self.font_path is None:
            self._font_cache[size_px] = None
            return None
        try:
            layout = getattr(getattr(ImageFont, "Layout", None), "RAQM", None)
            font = ImageFont.truetype(
                str(self.font_path),
                size_px,
                layout_engine=layout,
            )
        except (OSError, TypeError, ValueError):
            try:
                font = ImageFont.truetype(str(self.font_path), size_px)
            except (OSError, TypeError, ValueError):
                font = None
        self._font_cache[size_px] = font
        return font

    def _resolve_font_path(self) -> Path | None:
        explicit = os.getenv("HEXA_TEXT_FONT_FILE")
        if explicit:
            path = Path(explicit).expanduser()
            if path.is_file():
                return path

        direct_dirs: list[Path] = []
        windir = os.getenv("WINDIR")
        if windir:
            direct_dirs.append(Path(windir) / "Fonts")
        direct_dirs.extend([
            Path("/usr/share/fonts/truetype/noto"),
            Path("/usr/local/share/fonts"),
            Path.home() / ".fonts",
            Path.home() / ".local/share/fonts",
            Path("/Library/Fonts"),
            Path("/System/Library/Fonts"),
        ])
        for directory in direct_dirs:
            for name in self._FONT_FILENAMES:
                path = directory / name
                if path.is_file():
                    return path

        root = Path("/usr/share/fonts")
        if root.is_dir():
            for name in self._FONT_FILENAMES:
                match = next(root.rglob(name), None)
                if match is not None and match.is_file():
                    return match
        return None

    @staticmethod
    def _contains_arabic(value: str) -> bool:
        return any(
            "\u0600" <= char <= "\u06ff"
            or "\u0750" <= char <= "\u077f"
            or "\u08a0" <= char <= "\u08ff"
            for char in value
        )
