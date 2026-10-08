# Vendored production fonts

Editorial text is planned (HarfBuzz measurement) and rendered (libass `fontsdir`) with
exactly these files. No operating-system font is ever used for text.

| File | Family (name ID 1) | Version | Source | SHA-256 |
|---|---|---|---|---|
| `NotoKufiArabic-ExtraBold.ttf` | Noto Kufi Arabic ExtraBold | 2.110 | https://notofonts.github.io/arabic/fonts/NotoKufiArabic/hinted/ttf/ | `2fe7b7bddf2e5c7b8e221aafe091282403ebf4d4bf01dca68270b31452a7e8e0` |
| `NotoSans-ExtraBold.ttf` | Noto Sans ExtraBold | 2.015 | https://notofonts.github.io/latin-greek-cyrillic/fonts/NotoSans/hinted/ttf/ | `9ac0b0f9844abb98395b45a684b1dff821d8b4f2b8ab16ad7503fa33b009b602` |

Both are Copyright 2022 The Noto Project Authors and licensed under the SIL Open Font
License 1.1 (`OFL.txt`, which must ship with the fonts). No Reserved Font Name is declared;
the files are redistributed unmodified.

Face selection is per line, never per glyph: Arabic (with digits/Arabic punctuation) uses
Noto Kufi Arabic; text it cannot draw uses Noto Sans when Noto Sans covers every character;
anything else (e.g. Arabic mixed with Latin in one line) is not shown.
