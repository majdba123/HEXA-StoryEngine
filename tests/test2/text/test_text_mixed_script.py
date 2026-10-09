"""Roadmap V2 Sprint 6.1 - deterministic mixed-script editorial text.

One semantic cue stays one line drawn by exactly one vendored face: Kufi (Arabic, digits,
Arabic punctuation), Noto Sans (Latin-only lines) or the derived coverage merge of both
for mixed lines. libass applies Unicode BiDi to the whole line; the measurement model
reproduces it (UAX #9) and is checked against encoded frames.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from app.composition.text_director import TextPlacementDirector
from app.models import TextCue
from app.render.text import TextRenderer
from app.shared.handoff_text import TextHandoffMixin
from app.text.metrics import PRODUCTION_FONT_DIR, TextTypographyMetrics, _bidi_runs
from tests.test2.text.test_text_v2 import _render_ass

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg required")
ROOT = Path(__file__).resolve().parents[3]
KUFI, SANS, MIXED = "Noto Kufi Arabic ExtraBold", "Noto Sans ExtraBold", "HEXA Mixed ExtraBold"

REQUIRED = {
    "كلمة مرور": KUFI,
    "VPN": SANS,
    "خصم 50%": MIXED,
    "VPN آمن": MIXED,
    "Windows آمن": MIXED,
    "استخدم Windows 11": MIXED,
    "خصم $50": MIXED,
    "10,000$": SANS,
    "(2FA)": SANS,
    "فعّل (2FA)": MIXED,
    "CVE-2026-1234": SANS,
    "IP Address داخلي": MIXED,
    "خصم ٥٠٪": KUFI,
    "تُستخدم VPN": MIXED,
    "VPN، آمن؟": MIXED,
    "استخدم VPN على Windows 11": MIXED,
    "برامج الـBug Bounty": MIXED,
}


@pytest.mark.parametrize("text,family", sorted(REQUIRED.items()))
def test_each_line_gets_exactly_one_vendored_face(text: str, family: str) -> None:
    assert TextTypographyMetrics().face_for(text).family == family


def test_mono_script_lines_keep_their_sprint6_faces() -> None:
    metrics = TextTypographyMetrics()
    for text in ("رسالة", "طلب فدية", "سرقة حسابات", "كلمة مرور", "1000 ريال", "تُستخدم"):
        assert metrics.face_for(text).family == KUFI
    for text in ("Bug Bounty", "VPN", "Windows 11"):
        assert metrics.face_for(text).family == SANS


def test_unsupported_glyph_has_no_face_and_is_never_handed_to_libass(tmp_path: Path) -> None:
    from tests.test2.text.test_renderer import _plan as renderer_plan

    metrics = TextTypographyMetrics()
    for text in ("آمن 🔒", "VPN ★", "قفل ⌘"):
        assert metrics.face_for(text) is None and metrics.layout(text) is None
    plan = renderer_plan(tmp_path)
    cue = plan.text.cues[0]
    plan.text.cues[0] = cue.model_copy(update={"text": "آمن 🔒", "tokens": []})
    plan.text_motion[0] = plan.text_motion[0].model_copy(update={"tokens": []})
    assert TextRenderer().write_beat_ass(plan, plan.story[0], segment_start=0.0, duration=1.5,
                                         output=tmp_path / "x.ass") is None
    with pytest.raises(Exception) as failure:
        TextHandoffMixin.require_text_render_contract(
            story=plan.story, assets=plan.assets, text=plan.text,
            text_composition=plan.text_composition, text_motion=plan.text_motion,
        )
    assert "text_glyphs_outside_production_font" in str(failure.value.__dict__) + str(failure.value)


@pytest.mark.parametrize("text,expected", [
    ("خصم 50%", [("%", True), ("50", False), ("خصم ", True)]),
    ("VPN آمن", [(" آمن", True), ("VPN", False)]),
    ("استخدم VPN الآن", [(" الآن", True), ("VPN", False), ("استخدم ", True)]),
    ("Windows 11 آمن", [(" آمن", True), ("Windows 11", False)]),
    ("فعّل (2FA)", [(")", True), ("2FA", False), ("فعّل (", True)]),
    ("10,000$", [("10,000$", False)]),
    ("CVE-2026-1234", [("CVE-2026-1234", False)]),
    ("1000 ريال", [(" ريال", True), ("1000", False)]),
    # Neutral space between R and L takes the RTL paragraph direction (N2); the damma
    # stays on its base (W1).
    ("تُستخدم VPN", [("VPN", False), ("تُستخدم ", True)]),
])
def test_bidi_runs_follow_uax9_in_visual_order(text: str, expected) -> None:
    assert _bidi_runs(text, TextTypographyMetrics.contains_arabic(text)) == expected


def test_combining_marks_never_leave_their_base() -> None:
    for text in ("تُستخدم VPN", "فعّل (2FA)", "VPNً آمن"):
        for run, _ in _bidi_runs(text, True):
            assert not run or not run[0].strip() or not __import__("unicodedata").combining(run[0])


def test_mixed_cue_keeps_one_semantic_cue_and_one_box() -> None:
    cue = TextCue(id="text-001", beat_id="beat-001", text="خصم 50% على VPN", semantic_type="emphasis",
                  source_char_start=0, source_char_end=16, spoken_start=0.2, spoken_end=0.9,
                  emphasis_time=0.2, style_id="emphasis", priority=75)
    width, height = TextPlacementDirector.estimated_box(cue, scale=1.0)
    ink = TextTypographyMetrics().layout(cue.text, style_id="emphasis")
    assert abs(width - (ink.width + 28.0) / 1920) < 1e-9
    assert abs(height - (ink.height + 34.0) / 1080) < 1e-9


def test_mixed_face_build_is_reproducible_and_vendored() -> None:
    assert (PRODUCTION_FONT_DIR / "HEXAMixed-ExtraBold.ttf").is_file()
    result = subprocess.run([sys.executable, str(ROOT / "tools" / "build_mixed_text_font.py"), "--check"],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_mixed_face_keeps_kufi_glyph_ownership_and_metrics() -> None:
    from fontTools.ttLib import TTFont

    kufi = TTFont(PRODUCTION_FONT_DIR / "NotoKufiArabic-ExtraBold.ttf")
    mixed = TTFont(PRODUCTION_FONT_DIR / "HEXAMixed-ExtraBold.ttf")
    assert mixed["OS/2"].usWinAscent == kufi["OS/2"].usWinAscent
    assert mixed["OS/2"].usWinDescent == kufi["OS/2"].usWinDescent
    assert mixed["head"].unitsPerEm == kufi["head"].unitsPerEm
    kufi_cmap, mixed_cmap = kufi.getBestCmap(), mixed.getBestCmap()
    for code in (ord("خ"), ord("0"), ord("٪"), ord(" ")):
        assert kufi["glyf"][kufi_cmap[code]].numberOfContours == mixed["glyf"][mixed_cmap[code]].numberOfContours
    for char in "%$()VPN":
        assert ord(char) in mixed_cmap


def _mixed_plan(tmp_path: Path, text: str):
    from tests.test2.text.test_renderer import _plan as renderer_plan

    plan = renderer_plan(tmp_path)
    cue = plan.text.cues[0]
    words = text.split()
    tokens = [token.model_copy(update={"text": word}) for token, word in zip(cue.tokens * 4, words)]
    starts = [cue.spoken_start + 0.12 * index for index in range(len(words))]
    tokens = [token.model_copy(update={"spoken_start": start, "spoken_end": start + 0.1})
              for token, start in zip(tokens, starts)]
    plan.text.cues[0] = cue.model_copy(update={"text": text, "tokens": tokens, "style_id": "emphasis",
                                               "semantic_type": "emphasis"})
    motion = plan.text_motion[0]
    plan.text_motion[0] = motion.model_copy(update={"tokens": [
        mt.model_copy(update={"text": word, "start": start, "end": start + 0.1})
        for mt, word, start in zip(motion.tokens * 4, words, starts)]})
    return plan


@pytest.mark.parametrize("text", ["استخدم VPN على Windows 11", "خصم 50% على VPN"])
def test_mixed_reveal_states_use_one_face_and_keep_the_reading_edge(tmp_path: Path, text: str) -> None:
    plan = _mixed_plan(tmp_path, text)
    payload = TextRenderer().write_beat_ass(plan, plan.story[0], segment_start=0.0, duration=3.0,
                                            output=tmp_path / "m.ass").read_text(encoding="utf-8")
    metrics = TextTypographyMetrics()
    face = metrics.face_for(text)
    item = plan.text_composition[0].items[0]
    lines = [row for row in payload.splitlines() if row.startswith("Dialogue:")]
    assert len(lines) == len(text.split())
    edges = []
    for line in lines:
        tags = re.search(r"\{([^}]*)\}", line).group(1)
        assert chr(92) + "fn" + MIXED in tags  # every state is drawn by the cue's face
        assert tags.count(chr(92) + "fn") == 1  # never a font switch inside the line
        state = line.split("}", 1)[1].strip("\u2067\u2069")
        x = float(re.search(r"\\(?:move|pos)\((-?\d+),", tags).group(1))
        if "\\move(" in tags:
            x = float(re.search(r"\\move\(-?\d+,-?\d+,(-?\d+),", tags).group(1))
        layout = metrics.layout(state, style_id="emphasis", font_scale=item.font_scale, rtl=True, face=face)
        edges.append(x + layout.ink_right)
    assert max(edges) - min(edges) <= 1.0


@needs_ffmpeg
@pytest.mark.parametrize("text", sorted(REQUIRED))
def test_encoded_mixed_line_matches_measurement_and_vendored_fonts_only(tmp_path: Path, text: str) -> None:
    renderer = TextRenderer()
    metrics = TextTypographyMetrics()
    face = metrics.face_for(text)
    rtl = metrics.contains_arabic(text)
    face_tags = "" if face.family == KUFI else chr(92) + "fn" + face.family + chr(92) + "fs" + str(
        metrics.font_size(face, 178))
    tags = chr(92) + "an4" + face_tags + chr(92) + "pos(200,540)" + chr(92) + "blur0"
    image, log = _render_ass(tmp_path, [renderer._dialogue(0, 1, "Emphasis", tags,
                                                           renderer._directional_text(text, rtl))])
    ys, xs = np.where(np.abs(image - 128) > 24)
    layout = metrics.layout(text, style_id="emphasis")
    predicted = (200 + layout.ink_left, 540 + layout.ink_top, 200 + layout.ink_right, 540 + layout.ink_bottom)
    actual = (xs.min(), ys.min(), xs.max() + 1, ys.max() + 1)
    assert max(abs(a - p) for a, p in zip(actual, predicted)) <= 3.0
    chosen = [line.split("->")[-1] for line in log.splitlines() if "fontselect" in line]
    assert chosen
    vendored = ("NotoKufiArabic-ExtraBold", "NotoSans-ExtraBold", "HEXAMixed-ExtraBold")
    assert all(any(name in line for name in vendored) for line in chosen)
    assert not any(bad in line for line in chosen for bad in ("Arial", "DejaVu", "Liberation", "Segoe"))


@needs_ffmpeg
def test_encoded_rtl_order_puts_logical_first_segment_on_the_right(tmp_path: Path) -> None:
    renderer = TextRenderer()
    metrics = TextTypographyMetrics()
    face = metrics.face_for("VPN آمن")
    tags = chr(92) + "an4" + chr(92) + "fn" + face.family + chr(92) + "pos(200,540)" + chr(92) + "blur0"
    image, _ = _render_ass(tmp_path, [renderer._dialogue(0, 1, "Emphasis", tags,
                                                         renderer._directional_text("VPN آمن", True))])
    line = metrics.layout("VPN آمن", style_id="emphasis")
    vpn = metrics.layout("VPN", style_id="emphasis", face=face, rtl=False)
    # Draw "VPN" alone so that its ink right edge sits where the line's ink right edge is:
    # if "VPN" (logical first) is the rightmost segment the two right ends coincide.
    x = round(200 + line.ink_right - vpn.ink_right)
    solo = chr(92) + "an4" + chr(92) + "fn" + face.family + chr(92) + f"pos({x},540)" + chr(92) + "blur0"
    (tmp_path / "solo").mkdir()
    alone, _ = _render_ass(tmp_path / "solo", [renderer._dialogue(0, 1, "Emphasis", solo, "VPN")])
    right = slice(int(200 + line.ink_right - vpn.width) + 4, int(200 + line.ink_right) - 2)
    assert np.mean(np.abs(image[:, right] - alone[:, right])) < 2.0
