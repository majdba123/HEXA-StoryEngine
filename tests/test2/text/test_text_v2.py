"""Roadmap V2 Sprint 6 - Text V2 behavioural contracts.

Selection authority, abstention, readability, typography measurement and rendering of
the vendored production font. Encoded checks render through the production libass path.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from app.composition import TextCompositionPlanner
from app.models import (
    CompositionBeat,
    LayoutItem,
    MotionCue,
    MotionSegment,
    SceneSource,
    StoryBeat,
    TextCue,
    Transcript,
    TranscriptSegment,
    TranscriptWord,
)
from app.render.text import TextRenderer
from app.text import TextPlanner
from app.text.metrics import PRODUCTION_FONT_DIR, PRODUCTION_FONT_FAMILY, TextTypographyMetrics
from app.text.semantic import TextSemanticSelector
from app.text.timing import TextVisibilityPolicy
from tests.support.canonical_package import canonical_package

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg required")


# -- builders ------------------------------------------------------------------------------
def _transcript(script: str, *, step: float = 0.6, word: float = 0.42) -> Transcript:
    matches = list(re.finditer(r"\S+", script))
    words = [
        TranscriptWord(start=i * step, end=i * step + word, text=m.group(),
                       char_start=m.start(), char_end=m.end())
        for i, m in enumerate(matches)
    ]
    return Transcript(
        language="ar", duration=words[-1].end + 0.6,
        segments=[TranscriptSegment(start=0.0, end=words[-1].end, text=script, char_start=0,
                                    char_end=len(script), words=words)],
        words=words, timing_source="forced_alignment",
    )


def _beat(transcript: Transcript, *, end: float | None = None) -> StoryBeat:
    return StoryBeat(
        id="beat-001", scene_id="scene-001", start=0.0,
        end=transcript.duration if end is None else end,
        audio_start=0.0, audio_end=transcript.words[-1].end,
        narration=transcript.segments[0].text, action="EXPLAIN",
    )


def _span(script: str, phrase: str, occurrence: int = 0) -> dict:
    start = -1
    for _ in range(occurrence + 1):
        start = script.index(phrase, start + 1)
    return {"char_start": start, "char_end": start + len(phrase)}


def _package(script: str, assets: list[dict], *, text_anchor: str | None = None,
             leader: str | None = None, authoritative: bool = True):
    scene = SceneSource(id="scene-001", image_path=Path("scene.png"), order=1,
                        script_char_start=0, script_char_end=len(script))
    rows = []
    for index, row in enumerate(assets, start=1):
        rows.append({
            "scene_id": scene.id, "semantic_group_id": "group-1", "sequence_order": index,
            "binding_type": "EXPLICIT", "confidence": 1.0, "visual_focus": "PRIMARY", **row,
        })
    events = []
    if text_anchor or leader:
        events.append({"semantic_event_id": "event-1", "script_text": script,
                       "visual_leader_asset_id": leader or text_anchor,
                       "text_anchor_asset_id": text_anchor})
    return canonical_package(
        root=Path("/tmp"), package_id="text-v2", scenes=[scene], script=script,
        authoritative_semantics=authoritative,
        semantics={"scenes": [{
            "scene_id": scene.id,
            "semantic_groups": [{"semantic_group_id": "group-1", "script_text": script,
                                 "animation_policy": "SEQUENTIAL_WITHIN_PHRASE",
                                 "asset_ids": [row["asset_id"] for row in assets]}],
            "semantic_events": events,
            "assets": rows,
        }]},
    )


def _asset(asset_id: str, script: str, phrase: str, *, granularity: str, role: str = "OBJECT",
           occurrence: int = 0, concept: str = "visual") -> dict:
    return {"asset_id": asset_id, "semantic_role": role, "anchor_granularity": granularity,
            "semantic_meaning": concept, "visual_concept": concept, "script_text": phrase,
            "script_span": _span(script, phrase, occurrence)}


def _select(script: str, assets: list[dict], **kwargs):
    transcript = _transcript(script, **{k: v for k, v in kwargs.items() if k in {"step", "word"}})
    package = _package(script, assets, text_anchor=kwargs.get("text_anchor"),
                       leader=kwargs.get("leader"))
    return TextSemanticSelector().select(_beat(transcript), transcript, package=package)


def _plan(script: str, assets: list[dict], **kwargs):
    transcript = _transcript(script, **{k: v for k, v in kwargs.items() if k in {"step", "word"}})
    package = _package(script, assets, text_anchor=kwargs.get("text_anchor"))
    planner = TextPlanner()
    plan = planner.plan(transcript=transcript, story=[_beat(transcript, end=kwargs.get("beat_end"))],
                        package=package)
    return plan, planner


def _cue(text: str, start: float, end: float, *, cue_id: str = "text-001",
         semantic_type: str = "emphasis") -> TextCue:
    return TextCue(id=cue_id, beat_id="beat-001", text=text, semantic_type=semantic_type,
                   source_char_start=0, source_char_end=len(text), spoken_start=start,
                   spoken_end=end, emphasis_time=start, style_id=semantic_type, priority=75)


# -- 1-13: semantic authority, abstention, density ------------------------------------------
def test_no_structured_semantic_cue_means_no_text() -> None:
    # Only a bare verb trigger and a pronoun are bound: nothing deserves screen space.
    script = "أنا قلت إنه يشتغل"
    assets = [_asset("me", script, "أنا", granularity="EXACT_WORD", role="CHARACTER"),
              _asset("run", script, "يشتغل", granularity="EXACT_WORD", role="ACTION")]
    assert _select(script, assets) == []


def test_exact_text_anchor_phrase_is_authoritative() -> None:
    script = "المهاجم استخدم كلمة مرور ضعيفة للدخول"
    assets = [_asset("lock", script, "كلمة مرور ضعيفة", granularity="EXACT_PHRASE", role="PRIMARY"),
              _asset("door", script, "للدخول", granularity="EXACT_WORD")]
    picked = _select(script, assets, text_anchor="lock")
    assert [row.display_text for row in picked][0] == "كلمة مرور ضعيفة"
    assert picked[0].authority_rank == 5
    assert picked[0].provenance == "exact_asset_span:EXACT_PHRASE"


def test_leader_anchor_is_used_when_no_text_anchor_role_exists() -> None:
    script = "الشركة فقدت ملفات حساسة"
    assets = [_asset("files", script, "ملفات حساسة", granularity="EXACT_PHRASE", role="PRIMARY"),
              _asset("co", script, "الشركة", granularity="EXACT_WORD", role="CHARACTER")]
    picked = _select(script, assets, leader="files")
    files = next(row for row in picked if row.display_text == "ملفات حساسة")
    assert files.authority_rank == 4  # LEADER evidence, below an explicit TEXT_ANCHOR
    assert files.score >= max(row.score for row in picked if row is not files)


def test_ambiguous_binding_is_never_used_as_label() -> None:
    script = "شيء غامض ظهر فجأة"
    asset = _asset("odd", script, "شيء غامض", granularity="EXACT_PHRASE")
    asset["binding_type"] = "AMBIGUOUS"
    assert all(row.display_text != "شيء غامض" for row in _select(script, [asset]))


def test_warning_amount_cue_keeps_value_unit_and_state() -> None:
    script = "الرصيد فيه 300 ريال منها محجوزة"
    picked = _select(script, [_asset("cash", script, "300 ريال", granularity="EXACT_PHRASE")])
    assert any(row.display_text == "300 ريال محجوزة" and row.semantic_type == "warning_amount"
               for row in picked)


def test_amount_cue_from_spelled_number() -> None:
    script = "دفع خمسة آلاف ريال مرة واحدة"
    picked = _select(script, [_asset("cash", script, "خمسة آلاف ريال", granularity="EXACT_PHRASE")])
    assert any(row.display_text == "5000 ريال" and row.semantic_type == "amount" for row in picked)


def test_spelled_one_without_unit_is_an_article_not_a_number() -> None:
    script = "دليل واحد ما يكفي"
    picked = _select(script, [_asset("proof", script, "دليل واحد", granularity="EXACT_PHRASE")])
    assert all(row.display_text != "1" for row in picked)


def test_nominal_single_word_trigger_is_a_valid_keyword() -> None:
    script = "وصلت رسالة من البنك"
    picked = _select(script, [_asset("mail", script, "رسالة", granularity="EXACT_WORD")])
    assert [row.display_text for row in picked] == ["رسالة"]


def test_verb_single_word_trigger_times_the_visual_but_is_not_a_label() -> None:
    script = "الموظف اقتنع بسرعة"
    picked = _select(script, [_asset("idea", script, "اقتنع", granularity="EXACT_WORD")])
    assert all(row.display_text != "اقتنع" for row in picked)


def test_question_and_discourse_fragments_are_not_labels() -> None:
    script = "هل المهاجم يعني موجود"
    assets = [_asset("who", script, "هل المهاجم", granularity="EXACT_PHRASE", role="CHARACTER"),
              _asset("so", script, "يعني", granularity="EXACT_WORD")]
    texts = [row.display_text for row in _select(script, assets)]
    assert "هل المهاجم" not in texts and "يعني" not in texts


def test_negation_stays_with_its_predicate() -> None:
    script = "هذا التصرف غير قانوني أبدا"
    picked = _select(script, [_asset("law", script, "غير قانوني", granularity="EXACT_PHRASE")])
    assert [row.display_text for row in picked] == ["غير قانوني"]


def test_inner_conjunction_is_preserved_in_display() -> None:
    script = "الصفحة فيها الاسم والشعار نفسه"
    picked = _select(script, [_asset("brand", script, "الاسم والشعار", granularity="EXACT_PHRASE")])
    assert [row.display_text for row in picked] == ["الاسم والشعار"]


def test_displayed_text_keeps_source_diacritics() -> None:
    script = "البيانات تُستخدم بدون إذن"
    picked = _select(script, [_asset("use", script, "تُستخدم بدون إذن", granularity="EXACT_PHRASE")])
    assert picked and picked[0].display_text == "تُستخدم بدون إذن"


def test_duplicate_semantic_candidates_are_shown_once() -> None:
    script = "ثغرة خطيرة ثم ثغرة خطيرة"
    assets = [_asset("a", script, "ثغرة خطيرة", granularity="EXACT_PHRASE"),
              _asset("b", script, "ثغرة خطيرة", granularity="EXACT_PHRASE", occurrence=1)]
    picked = _select(script, assets)
    assert [row.display_text for row in picked].count("ثغرة خطيرة") == 1


def test_latin_label_is_kept_and_drawn_with_the_vendored_latin_face() -> None:
    script = "برنامج Bug Bounty يدفع للباحثين"
    picked = _select(script, [_asset("bb", script, "Bug Bounty", granularity="EXACT_PHRASE")])
    assert any(row.display_text == "Bug Bounty" for row in picked)
    assert TextTypographyMetrics().face_for("Bug Bounty").family == "Noto Sans ExtraBold"


def test_half_of_a_latin_term_is_never_shown() -> None:
    script = "وظهرت برامج الـBug Bounty للباحثين"
    asset = _asset("bb", script, "برامج الـBug Bounty", granularity="EXACT_PHRASE",
                   concept="bug bounty program portal")
    texts = [row.display_text for row in _select(script, [asset])]
    assert "Bounty" not in texts and "Bug" not in texts


def test_line_mixing_arabic_and_latin_uses_the_vendored_mixed_face() -> None:
    # Sprint 6.1: such lines were withheld (no single vendored face); the derived
    # vendored mixed face now draws them as one run, still without any OS fallback.
    script = "برنامج مكافآت Bug يدفع للباحثين"
    picked = _select(script, [_asset("bb", script, "مكافآت Bug", granularity="EXACT_PHRASE")])
    assert any(row.display_text == "مكافآت Bug" for row in picked)
    assert TextTypographyMetrics().face_for("مكافآت Bug").family == "HEXA Mixed ExtraBold"


def test_line_no_vendored_face_can_draw_still_abstains() -> None:
    script = "برنامج مكافآت 🔒 يدفع للباحثين"
    picked = _select(script, [_asset("bb", script, "مكافآت 🔒", granularity="EXACT_PHRASE")])
    assert all("🔒" not in row.display_text for row in picked)
    assert TextTypographyMetrics().face_for("مكافآت 🔒") is None


def _three_phrase_plan(step: float):
    script = "سرقة حسابات ثم تسريب بيانات ثم اختراق كامل"
    assets = [_asset("a", script, "سرقة حسابات", granularity="EXACT_PHRASE", role="RESULT"),
              _asset("b", script, "تسريب بيانات", granularity="EXACT_PHRASE"),
              _asset("c", script, "اختراق كامل", granularity="EXACT_PHRASE")]
    return _plan(script, assets, step=step)


def test_single_appearance_word_is_never_a_second_cue() -> None:
    script = "سرقة حسابات ثم وصلت رسالة بعدها بفترة"
    assets = [_asset("a", script, "سرقة حسابات", granularity="EXACT_PHRASE", role="RESULT"),
              _asset("b", script, "رسالة", granularity="EXACT_WORD")]
    plan, planner = _plan(script, assets, step=1.0)
    assert [cue.text for cue in plan.cues] == ["سرقة حسابات"]
    assert any(row["text"] == "رسالة" and row["reason"] == "accent_needs_phrase_evidence"
               for row in planner.abstentions)


def test_one_beat_never_shows_a_third_cue() -> None:
    plan, planner = _three_phrase_plan(step=1.2)
    assert 1 <= len(plan.cues) <= 2
    assert any(row["reason"] == "editorial_density" for row in planner.abstentions)


def test_justified_second_cue_is_a_distinct_readable_moment() -> None:
    plan, _ = _three_phrase_plan(step=1.2)
    if len(plan.cues) == 2:
        first, second = sorted(plan.cues, key=lambda cue: cue.spoken_start)
        assert second.spoken_start - first.spoken_start >= 0.45
        beat = _beat(_transcript("سرقة حسابات ثم تسريب بيانات ثم اختراق كامل", step=1.2))
        assert all(TextVisibilityPolicy.is_readable(cue, beat, plan.cues) for cue in plan.cues)


# -- 14-17: readability windows -----------------------------------------------------------
def test_readable_floor_counts_entrance_and_one_fixation_per_word() -> None:
    assert TextVisibilityPolicy.readable_floor(_cue("ثغرة", 0, 0.3)) == pytest.approx(0.49)
    assert TextVisibilityPolicy.readable_floor(_cue("كلمة مرور ضعيفة", 0, 0.3)) == pytest.approx(0.99)


def test_short_phrase_clipped_by_beat_end_abstains() -> None:
    script = "وصلت رسالة"
    plan, planner = _plan(script, [_asset("m", script, "رسالة", granularity="EXACT_WORD")],
                          step=0.6, beat_end=0.9)
    assert plan.cues == []
    assert planner.abstentions[0]["reason"] == "unreadable_window"


def test_long_phrase_with_room_is_kept_narration_locked() -> None:
    script = "المهاجم استخدم كلمة مرور ضعيفة للدخول"
    transcript = _transcript(script, step=0.6)
    plan, _ = _plan(script, [_asset("p", script, "كلمة مرور ضعيفة", granularity="EXACT_PHRASE")],
                    step=0.6)
    cue = next(cue for cue in plan.cues if cue.text == "كلمة مرور ضعيفة")
    assert cue.spoken_start == transcript.words[2].start
    assert cue.spoken_end == transcript.words[4].end


@pytest.mark.parametrize("step,kept", [(0.30, False), (0.70, True)])
def test_fast_and_slow_narration_change_only_abstention_not_timing(step: float, kept: bool) -> None:
    # Fast speech gives the first label 0.22 s before the stronger result replaces it.
    script = "الشركة تكتشفها بعد شهور طويلة"
    assets = [_asset("co", script, "الشركة", granularity="EXACT_PHRASE"),
              _asset("find", script, "تكتشفها", granularity="EXACT_PHRASE", role="RESULT")]
    plan, _ = _plan(script, assets, step=step)
    texts = [cue.text for cue in plan.cues]
    assert ("الشركة" in texts) is kept
    transcript = _transcript(script, step=step)
    for cue in plan.cues:  # narration authority: cues start exactly on their spoken word
        assert cue.spoken_start in {word.start for word in transcript.words}


# -- 18-22 / measurement: Arabic typography contract -------------------------------------------
@pytest.mark.parametrize("text", ["ثغرة", "كلمة مرور ضعيفة", "1000 ريال", "تُستخدم", "٣٠٠ ريال"])
def test_measurement_is_finite_positive_and_deterministic(text: str) -> None:
    metrics = TextTypographyMetrics()
    first = metrics.layout(text, style_id="emphasis", font_scale=0.74)
    again = TextTypographyMetrics().layout(text, style_id="emphasis", font_scale=0.74)
    assert first == again
    assert first.width > 0 and first.height > 0
    assert all(np.isfinite([first.ink_left, first.ink_right, first.ink_top, first.ink_bottom]))


def test_measurement_scales_glyphs_but_not_outline() -> None:
    metrics = TextTypographyMetrics()
    full = metrics.layout("ثغرة", style_id="emphasis", font_scale=1.0)
    half = metrics.layout("ثغرة", style_id="emphasis", font_scale=0.5)
    border = 2 * 9.0 + 1.2
    assert (half.width - border) == pytest.approx((full.width - border) * 0.5, rel=1e-6)


def test_face_selection_is_per_line_and_never_falls_back_to_the_os() -> None:
    metrics = TextTypographyMetrics()
    assert metrics.face_for("ضبط ١٠ أجهزة 2024").family == "Noto Kufi Arabic ExtraBold"
    assert metrics.face_for("Bug Bounty").family == "Noto Sans ExtraBold"
    assert metrics.face_for("50% (fee)").family == "Noto Sans ExtraBold"
    # Sprint 6.1: % is not in the Arabic face, so the line uses the vendored mixed face.
    assert metrics.face_for("خصم 50%").family == "HEXA Mixed ExtraBold"
    assert metrics.covers("خصم 50%")
    assert metrics.face_for("خصم 🔒") is None and not metrics.covers("خصم 🔒")
    latin = metrics.face_for("Bug Bounty")
    # Same em size as the Arabic face: Fontsize scales by the win-metric ratio.
    assert metrics.font_size(latin, 178) == round(178 * (1124 + 395) / (1507 + 650))


def test_renderer_uses_only_the_vendored_font_directory() -> None:
    renderer = TextRenderer()
    assert renderer.theme.font_family == PRODUCTION_FONT_FAMILY
    graph = renderer.ass_filter(Path("x.ass"), "in", "out")
    assert "fontsdir=" in graph
    assert PRODUCTION_FONT_DIR.joinpath("NotoKufiArabic-ExtraBold.ttf").is_file()
    assert PRODUCTION_FONT_DIR.joinpath("NotoSans-ExtraBold.ttf").is_file()
    assert PRODUCTION_FONT_DIR.joinpath("OFL.txt").is_file()


def _render_ass(tmp_path: Path, events: list[str], *, width=1920, height=1080) -> tuple[np.ndarray, str]:
    renderer = TextRenderer()

    class _Plan:
        projection = None

    _Plan.width, _Plan.height = width, height
    (tmp_path / "t.ass").write_text(renderer._document(_Plan, events), encoding="utf-8")
    graph = renderer.ass_filter(tmp_path / "t.ass", "0:v", "out").replace("[0:v]", "").replace("[out]", "")
    result = subprocess.run(
        ["ffmpeg", "-v", "verbose", "-y", "-f", "lavfi", "-i",
         f"color=c=0x808080:s={width}x{height}:d=0.1", "-vf", graph, "-frames:v", "1", "t.png"],
        cwd=tmp_path, capture_output=True, text=True, encoding="utf-8", errors="replace", check=True,
    )
    return np.asarray(Image.open(tmp_path / "t.png").convert("L")).astype(int), result.stderr


@needs_ffmpeg
@pytest.mark.parametrize("text,style,scale", [
    ("الاسم والشعار", "emphasis", 1.0),
    ("كلمة مرور ضعيفة", "keyword", 0.62),
    ("1000 ريال", "amount", 0.9),
    ("تُستخدم بدون إذن", "warning", 0.74),
    ("ضبط ١٠ أجهزة", "number", 0.56),
])
def test_encoded_libass_ink_matches_the_shared_measurement(tmp_path: Path, text, style, scale) -> None:
    renderer = TextRenderer()
    tags = f"\\an4\\fscx{round(scale * 100)}\\fscy{round(scale * 100)}\\pos(200,540)\\blur0"
    image, log = _render_ass(tmp_path, [renderer._dialogue(
        0, 1, renderer._ass_style_name(style), tags, renderer._directional_text(text, True))])
    ys, xs = np.where(np.abs(image - 128) > 24)
    layout = TextTypographyMetrics().layout(text, style_id=style, font_scale=scale)
    predicted = (200 + layout.ink_left, 540 + layout.ink_top, 200 + layout.ink_right, 540 + layout.ink_bottom)
    actual = (xs.min(), ys.min(), xs.max() + 1, ys.max() + 1)
    assert max(abs(a - p) for a, p in zip(actual, predicted)) <= 3.0
    selected = [line for line in log.splitlines() if "fontselect" in line]
    assert selected and all("NotoKufiArabic-ExtraBold" in line.split("->")[-1] for line in selected)


@needs_ffmpeg
def test_encoded_latin_line_uses_the_vendored_latin_face(tmp_path: Path) -> None:
    renderer = TextRenderer()
    metrics = TextTypographyMetrics()
    face = metrics.face_for("Bug Bounty")
    size = metrics.font_size(face, 178)
    tags = f"BSBSan4BSBSfn{face.family}BSBSfs{size}BSBSpos(200,540)BSBSblur0".replace("BSBS", chr(92))
    image, log = _render_ass(tmp_path, [renderer._dialogue(0, 1, "Emphasis", tags, "Bug Bounty")])
    ys, xs = np.where(np.abs(image - 128) > 24)
    layout = metrics.layout("Bug Bounty", style_id="emphasis")
    predicted = (200 + layout.ink_left, 540 + layout.ink_top, 200 + layout.ink_right, 540 + layout.ink_bottom)
    actual = (xs.min(), ys.min(), xs.max() + 1, ys.max() + 1)
    assert max(abs(a - p) for a, p in zip(actual, predicted)) <= 3.0
    chosen = [line.split("->")[-1] for line in log.splitlines() if "fontselect" in line]
    assert any("NotoSans-ExtraBold" in line for line in chosen)
    assert all("NotoSans-ExtraBold" in line or "NotoKufiArabic-ExtraBold" in line for line in chosen)


@needs_ffmpeg
def test_encoded_arabic_is_joined_rtl_and_not_reversed(tmp_path: Path) -> None:
    renderer = TextRenderer()
    words = "سرقة حسابات"
    tags = "\\an4\\pos(300,540)\\blur0"
    image, _ = _render_ass(tmp_path, [renderer._dialogue(
        0, 1, "Emphasis", tags, renderer._directional_text(words, True))])
    first_word = TextTypographyMetrics().layout("سرقة", style_id="emphasis")
    full = TextTypographyMetrics().layout(words, style_id="emphasis")
    columns = np.where((np.abs(image - 128) > 24).any(axis=0))[0]
    # RTL: the first logical word occupies the right end of the line.
    right_block_left = 300 + full.ink_right - first_word.width
    assert columns.max() + 1 == pytest.approx(300 + full.ink_right, abs=3)
    gap = [c for c in range(int(right_block_left) - 40, int(right_block_left)) if c not in set(columns)]
    assert gap, "a word space must separate the two RTL words"


# -- 23-33: placement and visible context ----------------------------------------------------
def _motion(asset_id: str, start: float) -> MotionCue:
    return MotionCue(beat_id="beat-001", asset_id=asset_id, kind="program_v3", start=start,
                     end=start + 0.3, segments=[MotionSegment(phase="ENTRY", start=start, end=start + 0.3)])


def test_cue_spoken_before_its_scene_opens_abstains() -> None:
    beat = StoryBeat(id="beat-001", scene_id="scene-001", start=0.0, end=3.0, narration="x",
                     action="EXPLAIN", primary_asset_ids=["hero"])
    visual = CompositionBeat(beat_id="beat-001", items=[
        LayoutItem(asset_id="hero", x=0.5, y=0.5, width=0.3, height=0.4, z=10)])
    early = _cue("ثغرة", 0.2, 0.6, cue_id="early")
    late = _cue("تسريب بيانات", 1.4, 1.9, cue_id="late")
    planner = TextCompositionPlanner()
    layout = planner.plan([beat], [visual], [early, late], [], visual_motion=[_motion("hero", 1.0)])
    placed = {item.text_cue_id for row in layout for item in row.items}
    assert placed == {"late"}
    assert planner.abstentions == [{
        "beat_id": "beat-001", "text_cue_id": "early", "reason": "before_scene_opener",
        "spoken_start": 0.2, "scene_opener": 1.0,
    }]


def test_cue_at_or_after_opener_is_placed() -> None:
    beat = StoryBeat(id="beat-001", scene_id="scene-001", start=0.0, end=3.0, narration="x",
                     action="EXPLAIN", primary_asset_ids=["hero"])
    visual = CompositionBeat(beat_id="beat-001", items=[
        LayoutItem(asset_id="hero", x=0.5, y=0.5, width=0.3, height=0.4, z=10)])
    planner = TextCompositionPlanner()
    layout = planner.plan([beat], [visual], [_cue("ثغرة", 1.0, 1.4)], [],
                          visual_motion=[_motion("hero", 1.0)])
    assert [item.text_cue_id for row in layout for item in row.items] == ["text-001"]
    assert planner.abstentions == []


# -- renderer geometry -------------------------------------------------------------------------
def test_reveal_states_keep_the_rtl_reading_edge_fixed(tmp_path: Path) -> None:
    from tests.test2.text.test_renderer import _plan as renderer_plan

    plan = renderer_plan(tmp_path)
    payload = TextRenderer().write_beat_ass(plan, plan.story[0], segment_start=0.0, duration=1.5,
                                            output=tmp_path / "s.ass").read_text(encoding="utf-8")
    metrics = TextTypographyMetrics()
    cue = plan.text.cues[0]
    item = plan.text_composition[0].items[0]
    edges = []
    for line in [row for row in payload.splitlines() if row.startswith("Dialogue:")]:
        tags = re.search(r"\{([^}]*)\}", line).group(1)
        text = line.split("}", 1)[1].strip("\u2067\u2069")
        x = float(re.search(r"\\(?:move|pos)\((-?\d+),", tags).group(1))
        if "\\move(" in tags:
            x = float(re.search(r"\\move\(-?\d+,-?\d+,(-?\d+),", tags).group(1))
        layout = metrics.layout(text, style_id=cue.style_id, font_scale=item.font_scale)
        edges.append(x + layout.ink_right)
        assert "\\an4" in tags
    assert len(edges) >= 2 and max(edges) - min(edges) <= 1.0


def test_safe_geometry_keeps_entry_path_inside_planned_box(tmp_path: Path) -> None:
    from tests.test2.text.test_renderer import _plan as renderer_plan

    plan = renderer_plan(tmp_path)
    item = plan.text_composition[0].items[0]
    cue = plan.text.cues[0]
    edge, centre, scale = TextRenderer()._safe_text_geometry(
        plan=plan, cue_text=cue.text, semantic_type=cue.semantic_type, style_id=cue.style_id,
        item=item, rtl=True, entry_strength=1.0,
    )
    layout = TextTypographyMetrics().layout(cue.text, style_id=cue.style_id, font_scale=scale)
    box_right = (item.x + item.max_width / 2) * plan.width
    box_left = (item.x - item.max_width / 2) * plan.width
    assert edge + 24 <= box_right + 0.5          # \move start (outermost) inside the box
    assert edge - layout.width >= box_left - 0.5  # resting ink inside the box


def _event_cue(cue_id: str, text: str, start: float, event: str) -> TextCue:
    return _cue(text, start, start + 0.4, cue_id=cue_id).model_copy(update={
        "package_evidence": [f"semantic_event:{event}",
                             "text_selection:exact_asset_span:EXACT_PHRASE"],
    })


def test_second_label_on_the_same_semantic_event_is_withheld() -> None:
    beat = StoryBeat(id="beat-001", scene_id="scene-001", start=0.0, end=6.0, narration="x",
                     action="EXPLAIN")
    first = _event_cue("a", "تسريب بيانات", 0.5, "E1")
    same = _event_cue("b", "اختراق كامل", 2.5, "E1")
    other = _event_cue("c", "طلب فدية", 2.5, "E2")
    abstentions: list[dict] = []
    kept = TextPlanner._apply_editorial_density(
        [first, same], {"beat-001": beat}, abstentions=abstentions)
    assert "b" not in {cue.id for cue in kept}
    assert any(row["text_cue_id"] == "b" and row["reason"] == "same_semantic_event" for row in abstentions)
    kept = TextPlanner._apply_editorial_density([first, other], {"beat-001": beat})
    assert "c" in {cue.id for cue in kept}
