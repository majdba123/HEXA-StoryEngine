from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import uharfbuzz as hb
from fontTools.ttLib import TTFont


_STYLE_SPECS: dict[str, tuple[int, float]] = {
    "keyword": (158, 8.0),
    "number": (188, 9.5),
    "amount": (188, 9.5),
    "warning_amount": (194, 9.8),
    "warning": (188, 9.5),
    "emphasis": (178, 9.0),
}

# The vendored production typefaces. Planning measures these exact files and the renderer
# hands their directory to libass (``fontsdir``), so no machine-local font can stand in.
PRODUCTION_FONT_DIR = Path(__file__).resolve().parent / "fonts"


@dataclass(frozen=True, slots=True)
class ProductionFace:
    family: str  # legacy (name ID 1) family: the name libass matches exactly
    file: Path


# Ordered: a line uses the first face that can draw every character of it (per line,
# never per glyph). The primary face also defines the shared em size. Mono-script lines
# keep their own Noto face; a line mixing Arabic with Latin/symbols uses the derived
# coverage merge of both (tools/build_mixed_text_font.py), because libass reorders
# segments when the font is switched inside a line.
PRODUCTION_FACES = (
    ProductionFace("Noto Kufi Arabic ExtraBold", PRODUCTION_FONT_DIR / "NotoKufiArabic-ExtraBold.ttf"),
    ProductionFace("Noto Sans ExtraBold", PRODUCTION_FONT_DIR / "NotoSans-ExtraBold.ttf"),
    ProductionFace("HEXA Mixed ExtraBold", PRODUCTION_FONT_DIR / "HEXAMixed-ExtraBold.ttf"),
)
PRODUCTION_FONT_FILE = PRODUCTION_FACES[0].file
PRODUCTION_FONT_FAMILY = PRODUCTION_FACES[0].family
# Render tokens shared with the ASS document: drop shadow offset in reference pixels.
TEXT_SHADOW_PX = 1.2

# Bidi isolates/marks (LRI, RLI, FSI, PDI, LRM, RLM, ALM): invisible, never measured.
_ISOLATES = frozenset(chr(code) for code in (0x2066, 0x2067, 0x2068, 0x2069, 0x200E, 0x200F, 0x061C))


@dataclass(frozen=True, slots=True)
class TextInkLayout:
    """Rendered footprint of one left-anchored (``an4``) ASS line, in pixels.

    Offsets are relative to the ``pos`` anchor (the line's left edge and its vertical
    middle) and include the outline and the drop shadow.
    """

    ink_left: float
    ink_right: float
    ink_top: float
    ink_bottom: float

    @property
    def width(self) -> float:
        return self.ink_right - self.ink_left

    @property
    def height(self) -> float:
        return self.ink_bottom - self.ink_top


@dataclass(frozen=True, slots=True)
class _Shaped:
    xmin: float
    xmax: float
    ymin: float
    ymax: float


class TextTypographyMetrics:
    """Measure text exactly as libass renders it with the vendored production faces.

    Shaping uses HarfBuzz on the same font file libass loads, with libass' sizing rule
    (``Fontsize`` spans the OS/2 Windows ascent+descent), its unscaled outline under
    ``ScaledBorderAndShadow`` and its middle-alignment line box. Simple bidi runs (Arabic
    with digits) are ordered the way FriBidi orders them. The renderer left-anchors every
    line, where libass glyph placement equals HarfBuzz placement. Each line uses exactly
    one vendored face (:meth:`face_for`); there is no per-glyph or OS fallback, and a line
    no single face can draw is reported by :meth:`covers` so Text abstains.
    """

    def __init__(self) -> None:
        self.faces = PRODUCTION_FACES

    @staticmethod
    def style_spec(
        style_id: str | None,
        semantic_type: str | None = None,
    ) -> tuple[int, float]:
        key = str(style_id or semantic_type or "keyword").strip().casefold()
        return _STYLE_SPECS.get(key, _STYLE_SPECS["keyword"])

    def face_for(self, text: str) -> ProductionFace | None:
        """The first production face that draws every visible character, else None."""
        visible = [
            ord(char) for char in str(text or "")
            if not (char.isspace() or char in _ISOLATES or unicodedata.category(char) == "Cf")
        ]
        for face in self.faces:
            cmap = _font_tables(str(face.file))[0]
            if all(code in cmap for code in visible):
                return face
        return None

    def covers(self, text: str) -> bool:
        """True when one production face can draw the whole line."""
        return self.face_for(text) is not None

    def font_size(self, face: ProductionFace, base_size: int) -> int:
        """ASS Fontsize giving ``face`` the same em size as the primary face."""
        if face == self.faces[0]:
            return int(base_size)
        _, primary_ascent, primary_descent = _font_tables(str(self.faces[0].file))
        _, ascent, descent = _font_tables(str(face.file))
        return max(1, round(base_size * (ascent + descent) / float(primary_ascent + primary_descent)))

    def measure(
        self,
        text: str,
        *,
        style_id: str | None = None,
        semantic_type: str | None = None,
        font_scale: float = 1.0,
    ) -> tuple[float, float]:
        layout = self.layout(
            text, style_id=style_id, semantic_type=semantic_type, font_scale=font_scale,
        )
        return (layout.width, layout.height) if layout is not None else (0.0, 0.0)

    def layout(
        self,
        text: str,
        *,
        style_id: str | None = None,
        semantic_type: str | None = None,
        font_scale: float = 1.0,
        pixel_scale: float = 1.0,
        rtl: bool | None = None,
        face: ProductionFace | None = None,
    ) -> TextInkLayout | None:
        """Ink footprint as rendered.

        ``rtl`` is the paragraph direction the renderer uses (an RLI isolate for any cue
        containing Arabic) and ``face`` the face of the whole cue (a reveal state is drawn
        with its cue's face); both default to the rules applied to ``text`` itself.
        """
        value = "".join(char for char in str(text or "").strip() if char not in _ISOLATES)
        face = face or self.face_for(value)
        if not value or face is None:
            return None
        base_size, outline = self.style_spec(style_id, semantic_type)
        scale = max(0.40, min(1.0, float(font_scale)))
        size = max(1, round(self.font_size(face, base_size) * pixel_scale))
        border = outline * pixel_scale
        shadow = TEXT_SHADOW_PX * pixel_scale
        _, win_ascent, win_descent = _font_tables(str(face.file))
        # libass: Fontsize is the OS/2 win ascent+descent height; \fscx/\fscy scale glyphs
        # only, while the outline width stays in script pixels.
        unit = size * scale / float(win_ascent + win_descent)
        paragraph_rtl = self.contains_arabic(value) if rtl is None else bool(rtl)
        shaped = _shape(str(face.file), value, paragraph_rtl)
        baseline = (win_ascent - win_descent) / 2.0 * unit
        return TextInkLayout(
            ink_left=shaped.xmin * unit - border,
            ink_right=shaped.xmax * unit + border + shadow,
            ink_top=baseline - shaped.ymax * unit - border,
            ink_bottom=baseline - shaped.ymin * unit + border + shadow,
        )

    @staticmethod
    def contains_arabic(value: str) -> bool:
        return any(
            "؀" <= char <= "ۿ"
            or "ݐ" <= char <= "ݿ"
            or "ࢠ" <= char <= "ࣿ"
            for char in value
        )


@lru_cache(maxsize=4)
def _font_tables(font_file: str) -> tuple[frozenset[int], int, int]:
    font = TTFont(font_file, lazy=True)
    try:
        cmap = frozenset(font.getBestCmap() or {})
        os2 = font["OS/2"]
        return cmap, int(os2.usWinAscent), int(os2.usWinDescent)
    finally:
        font.close()


@lru_cache(maxsize=4)
def _hb_font(font_file: str) -> hb.Font:
    return hb.Font(hb.Face(hb.Blob.from_file_path(font_file)))


_OPENING_BRACKETS = {"(": ")", "[": "]", "{": "}"}
_CLOSING_BRACKETS = {value: key for key, value in _OPENING_BRACKETS.items()}
_NEUTRALS = frozenset({"B", "S", "WS", "ON"})
_EXPLICIT = frozenset({"LRE", "RLE", "LRO", "RLO", "PDF", "LRI", "RLI", "FSI", "PDI", "BN"})


def _bidi_runs(text: str, rtl_paragraph: bool) -> list[tuple[str, bool]]:
    """Unicode BiDi (UAX #9) for one isolated paragraph -> (run, is_rtl) in visual order.

    Implements what FriBidi applies inside libass for editorial lines without explicit
    embeddings: W1-W7, N0 for paired ASCII brackets, N1-N2, I1-I2 and L2 reordering.
    Each run keeps logical order; HarfBuzz shapes it in its direction (mirroring
    brackets in RTL runs) exactly as libass does.
    """
    if not text:
        return []
    base = 1 if rtl_paragraph else 0
    edge = "R" if base else "L"
    types = ["ON" if kind in _EXPLICIT or not kind else kind
             for kind in (unicodedata.bidirectional(char) for char in text)]
    count = len(types)

    def last_strong(index: int, kinds: tuple[str, ...]) -> str:
        for position in range(index - 1, -1, -1):
            if types[position] in kinds:
                return types[position]
        return edge

    for index in range(count):  # W1: marks take the type of their base
        if types[index] == "NSM":
            types[index] = types[index - 1] if index else edge
    for index in range(count):  # W2
        if types[index] == "EN" and last_strong(index, ("R", "L", "AL")) == "AL":
            types[index] = "AN"
    types = ["R" if kind == "AL" else kind for kind in types]  # W3
    for index in range(1, count - 1):  # W4
        left, right = types[index - 1], types[index + 1]
        if types[index] == "ES" and left == right == "EN":
            types[index] = "EN"
        elif types[index] == "CS" and left == right and left in {"EN", "AN"}:
            types[index] = left
    index = 0
    while index < count:  # W5
        if types[index] != "ET":
            index += 1
            continue
        end = index
        while end < count and types[end] == "ET":
            end += 1
        if (index > 0 and types[index - 1] == "EN") or (end < count and types[end] == "EN"):
            types[index:end] = ["EN"] * (end - index)
        index = end
    types = ["ON" if kind in {"ES", "ET", "CS"} else kind for kind in types]  # W6
    for index in range(count):  # W7
        if types[index] == "EN" and last_strong(index, ("R", "L")) == "L":
            types[index] = "L"

    def strength(kind: str) -> str | None:
        return "L" if kind == "L" else "R" if kind in {"R", "EN", "AN"} else None

    stack: list[int] = []  # N0: bracket pairs, resolved in order of their opening bracket
    pairs: list[tuple[int, int]] = []
    for index, char in enumerate(text):
        if types[index] != "ON":
            continue
        if char in _OPENING_BRACKETS:
            stack.append(index)
        elif char in _CLOSING_BRACKETS:
            for depth in range(len(stack) - 1, -1, -1):
                if text[stack[depth]] == _CLOSING_BRACKETS[char]:
                    pairs.append((stack[depth], index))
                    del stack[depth:]
                    break
    for opening, closing in sorted(pairs):
        inside = {strength(types[i]) for i in range(opening + 1, closing)} - {None}
        if not inside:
            continue
        if edge in inside:
            resolved = edge
        else:
            before = next((strength(types[i]) for i in range(opening - 1, -1, -1)
                           if strength(types[i]) is not None), edge)
            resolved = before
        types[opening] = types[closing] = resolved
    index = 0
    while index < count:  # N1/N2
        if types[index] not in _NEUTRALS:
            index += 1
            continue
        end = index
        while end < count and types[end] in _NEUTRALS:
            end += 1
        before = strength(types[index - 1]) if index else edge
        after = strength(types[end]) if end < count else edge
        types[index:end] = [before if before == after else edge] * (end - index)
        index = end

    if base == 0:  # I1/I2
        levels = [1 if kind == "R" else 2 if kind in {"AN", "EN"} else 0 for kind in types]
    else:
        levels = [2 if kind in {"L", "EN", "AN"} else 1 for kind in types]
    runs: list[tuple[str, int]] = []
    for char, level in zip(text, levels):
        if runs and runs[-1][1] == level:
            runs[-1] = (runs[-1][0] + char, level)
        else:
            runs.append((char, level))
    lowest_odd = min(level for _, level in runs) | 1  # L2
    for level in range(max(level for _, level in runs), lowest_odd - 1, -1):
        index = 0
        while index < len(runs):
            if runs[index][1] < level:
                index += 1
                continue
            end = index
            while end < len(runs) and runs[end][1] >= level:
                end += 1
            runs[index:end] = runs[index:end][::-1]
            index = end
    return [(run, level % 2 == 1) for run, level in runs]


@lru_cache(maxsize=4096)
def _shape(font_file: str, text: str, rtl_paragraph: bool) -> _Shaped:
    font = _hb_font(font_file)
    pen = 0.0
    xmin = ymin = float("inf")
    xmax = ymax = float("-inf")
    for run, rtl in _bidi_runs(text, rtl_paragraph):
        buffer = hb.Buffer()
        buffer.add_str(run)
        buffer.guess_segment_properties()
        buffer.direction = "rtl" if rtl else "ltr"
        # libass disables the "kern" feature unless the script asks for it.
        hb.shape(font, buffer, {"kern": False})
        for info, position in zip(buffer.glyph_infos, buffer.glyph_positions):
            extents = font.get_glyph_extents(info.codepoint)
            if extents is not None and extents.width and extents.height:
                left = pen + position.x_offset + extents.x_bearing
                top = position.y_offset + extents.y_bearing
                xmin = min(xmin, left)
                xmax = max(xmax, left + extents.width)
                ymax = max(ymax, top)
                ymin = min(ymin, top + extents.height)
            pen += position.x_advance
    if xmin == float("inf"):
        xmin = xmax = ymin = ymax = 0.0
    return _Shaped(xmin=xmin, xmax=xmax, ymin=ymin, ymax=ymax)
