"""Restrained text appearance, anchoring and disappearance (visual sprint, Stage 2).

* The completed phrase is centred on its planned TextComposition box (boxes have a
  minimum label width, so an edge-aligned short word drifted up to 75 px off its anchor).
* A word revealed while the phrase's entry gesture still runs continues that gesture
  (26 of 304 later words used to make the line jump up to 24 px).
* Text Motion plans a short fade for each added word and an exit fade bounded by the
  phrase's readable hold; the renderer fades only the new word (clipped), so earlier
  words are never drawn twice, and lines mixing bidi directions keep a cut.
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

import numpy as np
import pytest

from app.motion.text import (
    ENTRY_FADE_MS,
    EXIT_FADE_HOLD_SHARE,
    EXIT_FADE_SECONDS,
    WORD_FADE_SECONDS,
    TextMotionPlanner,
)
from app.render.text import TextRenderer
from app.text.metrics import TextTypographyMetrics
from tests.test2.text.test_reading_order import _dialogues, _encoded_frame, _plan, _state

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg required")
SEQUENTIAL = [(0.35, 0.52), (0.70, 0.87), (0.95, 1.10)]


def _soft(plan, *, word_ms=100, exit_ms=150, entry_fade_ms=90):
    motion = plan.text_motion[0]
    plan.text_motion[0] = motion.model_copy(update={"params": {
        **motion.params, "word_fade_ms": word_ms, "exit_fade_ms": exit_ms, "entry_fade_ms": entry_fade_ms}})
    return plan


def _rows(plan, tmp_path):
    _path, lines = _dialogues(plan, tmp_path)
    return [_state(line) for line in lines]


def _rest_x(tags: str) -> int:
    rest = re.search(r"\\move\(-?\d+,-?\d+,(-?\d+),", tags) or re.search(r"\\pos\((-?\d+),", tags)
    return int(rest.group(1))


@pytest.mark.parametrize("text,rtl", [("الإذن", True), ("VPN", False)])
def test_short_phrase_is_centred_on_its_planned_box(tmp_path: Path, text: str, rtl: bool) -> None:
    plan = _plan(tmp_path, text, [(0.35, 0.52)])
    item = plan.text_composition[0].items[0]
    metrics = TextTypographyMetrics()
    rows = _rows(plan, tmp_path)
    scale = int(re.search(r"\\fscx(\d+)", rows[-1][2]).group(1)) / 100
    layout = metrics.layout(text, style_id="emphasis", font_scale=scale, rtl=rtl, face=metrics.face_for(text))
    centre = _rest_x(rows[-1][2]) + (layout.ink_left + layout.ink_right) / 2
    assert centre == pytest.approx(plan.width * item.x, abs=1.5)


def test_tight_box_keeps_the_whole_entry_path_inside(tmp_path: Path) -> None:
    plan = _plan(tmp_path, "المعرفة التقنية المتقدمة", SEQUENTIAL)
    item = plan.text_composition[0].items[0]
    plan.text_composition[0].items[0] = item.model_copy(update={"max_width": 0.40})
    renderer = TextRenderer()
    edge, _y, scale = renderer._safe_text_geometry(
        plan=plan, cue_text=plan.text.cues[0].text, semantic_type="emphasis", style_id="emphasis",
        item=plan.text_composition[0].items[0], rtl=True, entry_strength=1.0)
    layout = TextTypographyMetrics().layout(plan.text.cues[0].text, style_id="emphasis", font_scale=scale)
    box_right = plan.width * (0.5 + 0.20)
    assert edge + 24 <= box_right + 0.5  # path start (entry offset 24 px) stays in the box
    if layout.width + 48 <= plan.width * 0.40:
        assert edge == pytest.approx(plan.width * 0.5 + layout.width / 2, abs=0.5)


def test_word_inside_the_entry_gesture_continues_it_without_a_jump(tmp_path: Path) -> None:
    # second word 0.10 s into a 240 ms gesture
    plan = _plan(tmp_path, "نسمح له", [(0.35, 0.59), (0.45, 0.60)], entry_ms=240)
    rows = _rows(plan, tmp_path)
    metrics = TextTypographyMetrics()
    first, second = rows[0], rows[-1]
    m0 = re.search(r"\\move\((-?\d+),(-?\d+),(-?\d+),(-?\d+),0,(\d+)\)", first[2])
    m1 = re.search(r"\\move\((-?\d+),(-?\d+),(-?\d+),(-?\d+),0,(\d+)\)", second[2])
    assert m1, "the later state must continue the entry gesture"
    x0s, y0s, x0, y0, d0 = map(int, m0.groups())
    x1s, y1s, x1, y1, d1 = map(int, m1.groups())
    elapsed = second[0] - first[0]
    # reading edge (right ink edge) of the line just before and just after the switch
    scale = int(re.search(r"\\fscx(\d+)", first[2]).group(1)) / 100
    r0 = metrics.layout(first[3], style_id="emphasis", font_scale=scale).ink_right
    r1 = metrics.layout(second[3], style_id="emphasis", font_scale=scale).ink_right
    before = x0s + (x0 - x0s) * min(1.0, elapsed * 1000 / d0) + r0
    after = x1s + r1
    assert abs(before - after) <= 1.5
    assert y1s - y1 == pytest.approx((y0s - y0) * (1 - elapsed * 1000 / d0), abs=1.0)
    assert d1 == pytest.approx(d0 - elapsed * 1000, abs=1)


def test_added_word_fades_alone_and_earlier_words_are_drawn_once(tmp_path: Path) -> None:
    plan = _soft(_plan(tmp_path, "نسمح له يسوي", SEQUENTIAL, entry_ms=165))
    rows = _rows(plan, tmp_path)
    # state 1 | clipped word 2 fade | state 2 | clipped word 3 fade | state 3
    texts = [row[3] for row in rows]
    assert texts == ["نسمح", "نسمح له", "نسمح له", "نسمح له يسوي", "نسمح له يسوي"]
    clipped = [row for row in rows if "\\clip(" in row[2]]
    assert len(clipped) == 2 and all("\\fad(100,0)" in row[2] for row in clipped)
    # the unclipped states hand over seamlessly (each starts when the previous one ends)
    whole = [row for row in rows if "\\clip(" not in row[2]]
    assert all(b[0] == pytest.approx(a[1]) for a, b in zip(whole, whole[1:]))
    # never two events drawing the same words at the same time
    for fade in clipped:
        overlapping = [row for row in rows if row is not fade and row[0] < fade[1] - 1e-9 and row[1] > fade[0] + 1e-9]
        assert len(overlapping) == 1 and "\\clip(" not in overlapping[0][2]
        assert overlapping[0][3] != fade[3]  # the earlier state, not a copy of the new one


def test_mixed_direction_line_keeps_a_cut_for_added_words(tmp_path: Path) -> None:
    plan = _soft(_plan(tmp_path, "استخدم VPN الآن", SEQUENTIAL, entry_ms=165))
    rows = _rows(plan, tmp_path)
    assert not any("\\clip(" in row[2] for row in rows)
    assert [row[3] for row in rows] == ["استخدم", "استخدم VPN", "استخدم VPN الآن"]


def test_exit_fade_ends_at_visible_end_and_entry_fade_is_planned(tmp_path: Path) -> None:
    plan = _soft(_plan(tmp_path, "نسمح له يسوي", SEQUENTIAL, entry_ms=165), exit_ms=150, entry_fade_ms=90)
    rows = _rows(plan, tmp_path)
    assert "\\fad(90,0)" in rows[0][2]
    assert rows[-1][1] == pytest.approx(1.40)
    assert re.search(r"\\fad\(0,150\)", rows[-1][2])
    assert sum(1 for row in rows if re.search(r"\\fad\(\d+,[1-9]", row[2])) == 1


def test_plans_without_transition_fields_render_as_before(tmp_path: Path) -> None:
    rows = _rows(_plan(tmp_path, "نسمح له يسوي", SEQUENTIAL, entry_ms=165), tmp_path)
    assert [row[3] for row in rows] == ["نسمح", "نسمح له", "نسمح له يسوي"]
    assert not any("\\clip(" in row[2] for row in rows)
    assert re.search(r"\\fad\(\d+,0\)", rows[0][2]) and all("\\fad(" not in row[2] for row in rows[1:])


def test_text_motion_plans_bounded_transitions(tmp_path: Path) -> None:
    from tests.test2.text.test_renderer import _plan as renderer_plan

    plan = renderer_plan(tmp_path)
    cues = TextMotionPlanner().plan(plan.story, plan.text.cues, plan.text_composition)
    params = cues[0].params
    assert ENTRY_FADE_MS[0] <= params["entry_fade_ms"] <= ENTRY_FADE_MS[1]
    assert params["word_fade_ms"] == round(WORD_FADE_SECONDS * 1000)
    hold = params["visible_end"] - cues[0].tokens[-1].start
    assert 0 < params["exit_fade_ms"] <= round(1000 * min(EXIT_FADE_SECONDS, EXIT_FADE_HOLD_SHARE * hold))


@needs_ffmpeg
def test_encoded_word_fade_never_double_draws_the_earlier_words(tmp_path: Path) -> None:
    plan = _soft(_plan(tmp_path, "نسمح له يسوي", SEQUENTIAL, entry_ms=165))
    ass, lines = _dialogues(plan, tmp_path)
    rows = [_state(line) for line in lines]
    fade = next(row for row in rows if "\\clip(" in row[2])
    boundary = int(re.search(r"\\clip\(0,0,(\d+),", fade[2]).group(1))
    middle = _encoded_frame(tmp_path, ass, fade[0] + 0.05, plan)
    after = _encoded_frame(tmp_path, ass, fade[1] + 0.10, plan)
    before = _encoded_frame(tmp_path, ass, fade[0] - 0.05, plan)
    right = slice(boundary + 2, plan.width)
    left = slice(0, boundary - 2)
    # earlier words during the fade: exactly the earlier state's pixels (drawn once)
    assert float(np.max(np.abs(middle[:, right] - before[:, right]))) <= 2
    # after the handover: the same ink (each state is placed on whole pixels from its own
    # measurement, so edges may differ by a sub-pixel phase, but nothing is doubled or
    # re-sharpened: same ink mass, tiny mean difference)
    ink_before = float(np.sum(np.abs(before[:, right] - 128)))
    ink_after = float(np.sum(np.abs(after[:, right] - 128)))
    assert abs(ink_after - ink_before) <= 0.02 * ink_before
    assert float(np.mean(np.abs(after[:, right] - before[:, right]))) < 1.0
    # the new word is partly visible mid-fade: between the empty and the final picture
    empty = float(np.mean(np.abs(before[:, left] - after[:, left])))
    partial = float(np.mean(np.abs(middle[:, left] - after[:, left])))
    assert 0.15 * empty < partial < 0.85 * empty


@pytest.mark.parametrize("gap,expected", [(12.0, True), (1.5, True), (0.5, False), (-3.0, False)])
def test_added_word_clip_needs_a_gap_between_the_words(gap: float, expected: bool) -> None:
    # RTL: earlier words occupy [500, 900]; the new word (200 px of ink) ends ``gap`` left of them
    spans = {"old": (500.0, 900.0), "old new": (300.0 - gap, 900.0), "new": (0.0, 200.0)}
    clip = TextRenderer._added_word_clip(
        lambda text: spans[text], "old", "old new", "new", rtl=True, width=1920, height=1080,
        elapsed=None, gesture_ms=200, gesture_dx=20)
    assert bool(clip) is expected
    if expected:
        edge = int(re.search(r"\\clip\(0,0,(\d+),1080\)", clip).group(1))
        assert 500 - gap <= edge <= 500  # inside the gap, never into the earlier words


def test_added_word_clip_travels_with_a_running_entry_gesture() -> None:
    spans = {"old": (500.0, 900.0), "old new": (290.0, 900.0), "new": (0.0, 200.0)}
    clip = TextRenderer._added_word_clip(
        lambda text: spans[text], "old", "old new", "new", rtl=True, width=1920, height=1080,
        elapsed=0.05, gesture_ms=200, gesture_dx=20)
    start, rest = map(int, re.findall(r"\\clip\(0,0,(\d+),1080\)", clip))
    assert start - rest == 15 and "\\t(0,150," in clip
