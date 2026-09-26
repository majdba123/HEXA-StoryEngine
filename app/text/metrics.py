from __future__ import annotations

import os
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path

from PIL import ImageFont

from app.shared.process import run_hidden


_STYLE_SPECS: dict[str, tuple[int, float]] = {
    "keyword": (158, 8.0),
    "number": (188, 9.5),
    "amount": (188, 9.5),
    "warning_amount": (194, 9.8),
    "warning": (188, 9.5),
    "emphasis": (178, 9.0),
}


class TextTypographyMetrics:
    """Measure text with the same production font geometry used by libass.

    Placement used to estimate width from character count, which is not reliable for
    shaped Arabic Kufi text. Pillow+RAQM provides the closest available planning-time
    measurement. If the exact font cannot be located, a deliberately conservative
    fallback is used; rendering still applies a final safe-area clamp.
    """

    DEFAULT_FONT_FAMILY = "Noto Kufi Arabic Extra Bold"
    DEFAULT_FONT_FILENAMES = (
        "NotoKufiArabic-ExtraBold.ttf",
        "NotoKufiArabic-ExtraBold.otf",
        "Noto Kufi Arabic ExtraBold.ttf",
    )

    def __init__(self, *, font_family: str = DEFAULT_FONT_FAMILY) -> None:
        self.font_family = font_family
        self.font_path = self._resolve_font_path(font_family)

    @staticmethod
    def style_spec(
        style_id: str | None,
        semantic_type: str | None = None,
    ) -> tuple[int, float]:
        key = str(style_id or semantic_type or "keyword").strip().casefold()
        return _STYLE_SPECS.get(key, _STYLE_SPECS["keyword"])

    def measure(
        self,
        text: str,
        *,
        style_id: str | None = None,
        semantic_type: str | None = None,
        font_scale: float = 1.0,
    ) -> tuple[float, float]:
        base_size, base_outline = self.style_spec(style_id, semantic_type)
        scale = max(0.40, min(1.0, float(font_scale)))
        size = max(1, round(base_size * scale))
        stroke = max(0, round(base_outline * scale))
        value = str(text or "").strip()
        if not value:
            return (0.0, 0.0)

        if self.font_path is not None:
            measured = self._measure_font(self.font_path, value, size, stroke)
            if measured is not None:
                return measured
        return self._fallback_measure(value, size=size, stroke=stroke)

    @staticmethod
    @lru_cache(maxsize=1024)
    def _measure_font(
        font_path: str,
        text: str,
        size: int,
        stroke: int,
    ) -> tuple[float, float] | None:
        try:
            layout = getattr(ImageFont, "Layout", None)
            kwargs = {}
            if layout is not None and hasattr(layout, "RAQM"):
                kwargs["layout_engine"] = layout.RAQM
            font = ImageFont.truetype(font_path, size=size, **kwargs)
            direction = "rtl" if TextTypographyMetrics._contains_arabic(text) else "ltr"
            try:
                box = font.getbbox(text, direction=direction, stroke_width=stroke)
            except (TypeError, ValueError):
                box = font.getbbox(text, stroke_width=stroke)
            width = max(0.0, float(box[2] - box[0]))
            height = max(0.0, float(box[3] - box[1]))
            if width > 0.0 and height > 0.0:
                return (width, height)
        except (OSError, RuntimeError, ValueError):
            return None
        return None

    @staticmethod
    def _fallback_measure(text: str, *, size: int, stroke: int) -> tuple[float, float]:
        units = 0.0
        for char in text:
            if char.isspace():
                units += 0.36
            elif char.isdigit():
                units += 0.62
            elif char in ".,:;!?،؛؟-/":
                units += 0.34
            else:
                units += 0.70
        width = units * size + stroke * 2 + size * 0.10
        height = size * 1.30 + stroke * 2
        return (width, height)

    @classmethod
    @lru_cache(maxsize=8)
    def _resolve_font_path(cls, font_family: str) -> str | None:
        explicit = os.getenv("HEXA_TEXT_FONT_FILE")
        if explicit:
            path = Path(explicit).expanduser()
            if path.is_file():
                return str(path)

        roots = [
            Path("/usr/share/fonts"),
            Path("/usr/local/share/fonts"),
            Path.home() / ".fonts",
            Path.home() / ".local/share/fonts",
            Path("/Library/Fonts"),
            Path("/System/Library/Fonts"),
        ]
        windir = os.getenv("WINDIR")
        if windir:
            roots.append(Path(windir) / "Fonts")

        if "noto kufi arabic" in font_family.casefold():
            for root in roots:
                if not root.is_dir():
                    continue
                for filename in cls.DEFAULT_FONT_FILENAMES:
                    direct = root / filename
                    if direct.is_file():
                        return str(direct)
                    try:
                        match = next(root.rglob(filename), None)
                    except OSError:
                        match = None
                    if match is not None and match.is_file():
                        return str(match)

        if shutil.which("fc-match"):
            try:
                result = run_hidden(
                    ["fc-match", "-f", "%{file}", font_family],
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=2.0,
                )
                candidate = Path(result.stdout.strip())
                if candidate.is_file():
                    return str(candidate)
            except (OSError, subprocess.SubprocessError):
                pass

        return None

    @staticmethod
    def _contains_arabic(value: str) -> bool:
        return any(
            "\u0600" <= char <= "\u06ff"
            or "\u0750" <= char <= "\u077f"
            or "\u08a0" <= char <= "\u08ff"
            for char in value
        )
