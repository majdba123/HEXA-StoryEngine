# Vendored production fonts

Editorial text is planned (HarfBuzz measurement) and rendered (libass `fontsdir`) with
exactly these files. No operating-system font is ever used for text.

| File | Family (name ID 1) | Version | Source | SHA-256 |
|---|---|---|---|---|
| `NotoKufiArabic-ExtraBold.ttf` | Noto Kufi Arabic ExtraBold | 2.110 | https://notofonts.github.io/arabic/fonts/NotoKufiArabic/hinted/ttf/ | `2fe7b7bddf2e5c7b8e221aafe091282403ebf4d4bf01dca68270b31452a7e8e0` |
| `NotoSans-ExtraBold.ttf` | Noto Sans ExtraBold | 2.015 | https://notofonts.github.io/latin-greek-cyrillic/fonts/NotoSans/hinted/ttf/ | `9ac0b0f9844abb98395b45a684b1dff821d8b4f2b8ab16ad7503fa33b009b602` |
| `HEXAMixed-ExtraBold.ttf` | HEXA Mixed ExtraBold | 1.000 | built by `tools/build_mixed_text_font.py` from the two files above (manifest `HEXAMixed-ExtraBold.json`) | `d5eb686a77123f102c7ab4393df44ed70258603fde785f61e31e5bfd82411c07` |

The Noto files are Copyright 2022 The Noto Project Authors and licensed under the SIL Open
Font License 1.1 (`OFL.txt`, which must ship with the fonts). No Reserved Font Name is
declared; they are redistributed unmodified. `HEXA Mixed ExtraBold` is a Modified Version
under the same licence (it may not be sold by itself and stays under OFL 1.1): every glyph,
metric and layout table of Noto Kufi Arabic ExtraBold, plus the Noto Sans ExtraBold glyphs
for code points Kufi does not map. `python tools/build_mixed_text_font.py --check` proves
the vendored file is a byte-identical rebuild of the two sources.

Face selection is per line, never per glyph: Arabic (with digits/Arabic punctuation) uses
Noto Kufi Arabic; Latin-only lines use Noto Sans; a line mixing Arabic with Latin, `%`,
`$` or brackets uses HEXA Mixed (one font, so libass applies Unicode BiDi to the whole
line — switching fonts inside a line reorders its segments). A line no vendored face can
draw (e.g. an emoji) is not shown.
