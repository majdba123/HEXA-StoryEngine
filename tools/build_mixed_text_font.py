"""Build the vendored mixed-script text face from the two vendored Noto faces.

    python tools/build_mixed_text_font.py          # rebuild app/text/fonts/HEXAMixed-ExtraBold.ttf
    python tools/build_mixed_text_font.py --check  # fail if the vendored file differs

libass applies Unicode BiDi only within one font run: switching fonts inside a line with
override tags reorders the segments. A line that mixes Arabic with Latin, %, $ or
brackets therefore needs ONE face that draws every character. This face is Noto Kufi
Arabic ExtraBold (every code point it maps, its metrics and its layout tables) plus, for
code points Kufi does not map, the glyphs of Noto Sans ExtraBold. Ownership is decided by
coverage only, Kufi first, and is written to the build manifest. The output is
deterministic (fixed timestamps, stable ordering) and stays under the SIL OFL 1.1.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
import tempfile
from pathlib import Path

from fontTools import subset
from fontTools.merge import Merger
from fontTools.ttLib import TTFont

FONTS = Path(__file__).resolve().parents[1] / "app" / "text" / "fonts"
ARABIC = FONTS / "NotoKufiArabic-ExtraBold.ttf"
LATIN = FONTS / "NotoSans-ExtraBold.ttf"
OUTPUT = FONTS / "HEXAMixed-ExtraBold.ttf"
MANIFEST = FONTS / "HEXAMixed-ExtraBold.json"
FAMILY = "HEXA Mixed ExtraBold"
POSTSCRIPT = "HEXAMixed-ExtraBold"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build() -> tuple[bytes, dict]:
    arabic = TTFont(ARABIC)
    latin = TTFont(LATIN)
    arabic_cmap = set(arabic.getBestCmap())
    borrowed = sorted(set(latin.getBestCmap()) - arabic_cmap)

    options = subset.Options()
    options.layout_features = ["*"]
    options.name_IDs = ["*"]
    options.notdef_outline = True
    options.recalc_timestamp = False
    subsetter = subset.Subsetter(options)
    subsetter.populate(unicodes=borrowed)
    subsetter.subset(latin)

    with tempfile.TemporaryDirectory() as tmp:
        latin_path = Path(tmp) / "latin-subset.ttf"
        latin.save(latin_path)
        merged = Merger().merge([str(ARABIC), str(latin_path)])

    reference = TTFont(ARABIC)
    for table in ("head", "hhea", "OS/2"):
        # Kufi's vertical metrics define the line box, so Arabic sits exactly as in Kufi.
        merged[table] = reference[table]
    merged["head"].checkSumAdjustment = 0
    names = merged["name"]
    names.names = [record for record in names.names if record.nameID not in {1, 2, 3, 4, 6, 16, 17, 21, 22}]
    for name_id, value in (
        (1, FAMILY), (2, "Regular"), (3, f"{POSTSCRIPT};1.000"), (4, FAMILY), (6, POSTSCRIPT),
        (5, "Version 1.000; Noto Kufi Arabic 2.110 + Noto Sans 2.015 (coverage merge)"),
    ):
        names.setName(value, name_id, 3, 1, 0x409)

    merged.recalcTimestamp = False  # keep Kufi's head timestamps: byte-identical rebuilds
    stream = io.BytesIO()
    merged.save(stream, reorderTables=True)
    data = stream.getvalue()
    manifest = {
        "family": FAMILY,
        "sources": {
            ARABIC.name: _sha(ARABIC.read_bytes()),
            LATIN.name: _sha(LATIN.read_bytes()),
        },
        "owner_rule": "a code point mapped by Noto Kufi Arabic is drawn by it; otherwise by Noto Sans",
        "kufi_code_points": len(arabic_cmap),
        "borrowed_from_noto_sans": len(borrowed),
        "borrowed_ranges": _ranges(borrowed),
        "vertical_metrics": "Noto Kufi Arabic (head, hhea, OS/2)",
        "sha256": _sha(data),
    }
    return data, manifest


def _ranges(points: list[int]) -> list[str]:
    output: list[str] = []
    start = previous = None
    for point in points:
        if start is None:
            start = previous = point
        elif point == previous + 1:
            previous = point
        else:
            output.append(f"U+{start:04X}-U+{previous:04X}" if start != previous else f"U+{start:04X}")
            start = previous = point
    if start is not None:
        output.append(f"U+{start:04X}-U+{previous:04X}" if start != previous else f"U+{start:04X}")
    return output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    data, manifest = build()
    text = json.dumps(manifest, indent=1) + "\n"
    if args.check:
        same = OUTPUT.is_file() and OUTPUT.read_bytes() == data and MANIFEST.read_text(encoding="utf-8") == text
        print("vendored mixed face is reproducible" if same else "vendored mixed face differs from build")
        return 0 if same else 1
    OUTPUT.write_bytes(data)
    MANIFEST.write_text(text, encoding="utf-8")
    print(OUTPUT, manifest["sha256"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
