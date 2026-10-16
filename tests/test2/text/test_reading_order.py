"""Arabic reading order through Text Motion -> ASS -> libass -> encoded frame.

Regression: words spoken before their subject was recognisable start together (same
``start``); the renderer re-sorted the reveal states by (start, end), so the shorter second
word came first and libass shaped "المعرفة التقنية" as "التقنية المعرفة" (12 cues in 5
packages). Reveal states now follow the planned reading order and tied words appear
together; the render handoff rejects tokens that do not read as their cue.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from app.models import RenderPlan, TextMotionToken, TextTokenCue
from app.motion import TextMotionPlanner
from app.render.text import TextRenderer
from app.shared.handoff import LayerHandoffValidator
from app.text.metrics import TextTypographyMetrics
from tests.test2.integration.handoff_contract_support import expect_handoff_failure
from tests.test2.text.test_renderer import _plan as renderer_plan
from tests.test2.text.test_text_v2 import _render_ass

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg required")
FPS = 30


def _plan(tmp_path: Path, text: str, timing: list[tuple[float, float]], *, entry_ms: int = 240) -> RenderPlan:
    plan = renderer_plan(tmp_path)
    plan = plan.model_copy(update={"fps": FPS})
    cue = plan.text.cues[0]
    words = text.split()
    offset, cue_tokens = cue.source_char_start, []
    for word, (start, _end) in zip(words, timing):
        cue_tokens.append(TextTokenCue(text=word, source_char_start=offset, source_char_end=offset + len(word),
                                       spoken_start=start, spoken_end=start + 0.1))
        offset += len(word) + 1
    plan.text.cues[0] = cue.model_copy(update={
        "text": text, "tokens": cue_tokens, "style_id": "emphasis", "semantic_type": "emphasis",
        "source_char_end": offset - 1, "spoken_start": timing[0][0], "emphasis_time": timing[0][0]})
    motion = plan.text_motion[0]
    plan.text_motion[0] = motion.model_copy(update={
        "start": timing[0][0], "end": timing[0][1],
        "params": {**motion.params, "entry_duration_ms": entry_ms, "visible_end": 1.40},
        "tokens": [TextMotionToken(text=word, start=start, end=end, visible_end=1.40, kind="text_word_reveal_in")
                   for word, (start, end) in zip(words, timing)]})
    return plan


def _dialogues(plan: RenderPlan, tmp_path: Path) -> tuple[Path, list[str]]:
    path = TextRenderer().write_beat_ass(plan, plan.story[0], segment_start=0.0, duration=plan.duration,
                                         output=tmp_path / "beat.ass")
    return path, [row for row in path.read_text(encoding="utf-8").splitlines() if row.startswith("Dialogue:")]


def _seconds(value: str) -> float:
    hours, minutes, seconds = value.split(":")
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def _state(line: str) -> tuple[float, float, str, str]:
    fields = line.split(",", 9)
    tags = re.search(r"\{([^}]*)\}", fields[9]).group(1)
    return _seconds(fields[1]), _seconds(fields[2]), tags, fields[9].split("}", 1)[1].strip("\u2067\u2069")


TIED = [(0.35, 0.59), (0.35, 0.49)]                 # the Black Hat beat-002 pattern
TIED_TAIL = [(0.35, 0.59), (0.70, 0.87), (0.70, 0.84)]
NEAR_TIE = [(0.35, 0.59), (0.36, 0.50), (0.80, 0.95)]
SEQUENTIAL = [(0.35, 0.52), (0.70, 0.87), (0.95, 1.10)]


@pytest.mark.parametrize("text,timing,states", [
    ("المعرفة التقنية", TIED, ["المعرفة التقنية"]),
    ("يُستخدم هذا الوصول", TIED_TAIL, ["يُستخدم", "يُستخدم هذا الوصول"]),
    ("نسمح له يسوي", NEAR_TIE, ["نسمح له", "نسمح له يسوي"]),
    ("نسمح له يسوي", SEQUENTIAL, ["نسمح", "نسمح له", "نسمح له يسوي"]),
])
def test_reveal_states_are_reading_order_prefixes_without_overlap(tmp_path: Path, text, timing, states) -> None:
    _path, lines = _dialogues(_plan(tmp_path, text, timing), tmp_path)
    rows = [_state(line) for line in lines]
    assert [row[3] for row in rows] == states
    assert all(text.startswith(row[3]) for row in rows)
    # One state at a time: each ends exactly when the next begins, the last at visible_end.
    assert all(abs(a[1] - b[0]) < 1e-9 for a, b in zip(rows, rows[1:]))
    assert rows[-1][1] == pytest.approx(1.40)
    # Only the first state carries the entry gesture.
    assert "\\move(" in rows[0][2] and all("\\move(" not in row[2] for row in rows[1:])


def test_text_motion_keeps_reading_order_when_words_wait_for_their_subject(tmp_path: Path) -> None:
    plan = renderer_plan(tmp_path)
    cue = plan.text.cues[0].model_copy(update={"tokens": [
        TextTokenCue(text="المعرفة", source_char_start=0, source_char_end=7, spoken_start=3.50, spoken_end=3.90),
        TextTokenCue(text="التقنية", source_char_start=8, source_char_end=15, spoken_start=3.95, spoken_end=4.40),
    ], "text": "المعرفة التقنية", "semantic_type": "emphasis"})
    tokens = TextMotionPlanner()._token_motion(cue, 5.5, "REVEAL", first_duration=0.24, not_before=4.096)
    assert [token.text for token in tokens] == ["المعرفة", "التقنية"]
    assert [token.start for token in tokens] == [4.096, 4.096]
    assert all(b.start >= a.start for a, b in zip(tokens, tokens[1:]))


def test_render_handoff_rejects_tokens_that_do_not_read_as_their_cue(tmp_path: Path) -> None:
    plan = _plan(tmp_path, "المعرفة التقنية", TIED)
    motion = plan.text_motion[0]
    swapped = motion.model_copy(update={"tokens": list(reversed(motion.tokens))})
    LayerHandoffValidator.require_text_render_contract(
        story=plan.story, assets=plan.assets, text=plan.text,
        text_composition=plan.text_composition, text_motion=plan.text_motion)
    error = expect_handoff_failure(
        "TEXT_HANDOFF_CONTRACT_VIOLATIONS",
        lambda: LayerHandoffValidator.require_text_render_contract(
            story=plan.story, assets=plan.assets, text=plan.text,
            text_composition=plan.text_composition, text_motion=[swapped]),
    )
    assert any(row["kind"] == "text_motion_tokens_out_of_reading_order" for row in error.details["violations"])


def _encoded_frame(tmp_path: Path, ass: Path, t: float, plan: RenderPlan) -> np.ndarray:
    graph = TextRenderer.ass_filter(ass, "0:v", "out").replace("[0:v]", "").replace("[out]", "")
    out = tmp_path / f"f{round(t * FPS)}.png"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
         f"color=c=0x808080:s={plan.width}x{plan.height}:r={FPS}:d={plan.duration}",
         "-vf", f"{graph},select=eq(n\\,{round(t * FPS)})", "-frames:v", "1", "-fps_mode", "passthrough", out.name],
        cwd=tmp_path, capture_output=True, check=True,
    )
    return np.asarray(Image.open(out).convert("L")).astype(int)


def _first_word_on_the_right(tmp_path: Path, plan: RenderPlan, frame: np.ndarray, line: str) -> float:
    """Mean pixel difference between the right end of the encoded line and the logical first
    word drawn alone with its ink right edge on the line's ink right edge."""
    metrics = TextTypographyMetrics()
    _start, _end, tags, state = _state(line)
    scale = int(re.search(r"\\fscx(\d+)", tags).group(1)) / 100
    rest = re.search(r"\\move\(-?\d+,-?\d+,(-?\d+),(-?\d+)", tags) or re.search(r"\\pos\((-?\d+),(-?\d+)", tags)
    x, y = int(rest.group(1)), int(rest.group(2))
    blur = re.search(r"\\blur([\d.]+)", tags).group(1)
    first = plan.text.cues[0].text.split()[0]
    edge = x + metrics.layout(state, style_id="emphasis", font_scale=scale).ink_right
    word = metrics.layout(first, style_id="emphasis", font_scale=scale)
    solo_tags = f"\\an4\\fscx{round(scale * 100)}\\fscy{round(scale * 100)}\\pos({round(edge - word.ink_right)},{y})\\blur{blur}"
    renderer = TextRenderer()
    (tmp_path / "solo").mkdir(exist_ok=True)
    alone, _ = _render_ass(tmp_path / "solo", [renderer._dialogue(0, 1, "Emphasis", solo_tags,
                                                                  renderer._directional_text(first, True))],
                           width=plan.width, height=plan.height)
    right = slice(int(edge - word.width) + 4, int(edge) - 2)
    return float(np.mean(np.abs(frame[:, right] - alone[:, right])))


@needs_ffmpeg
@pytest.mark.parametrize("text,timing,times", [
    ("المعرفة التقنية", TIED, [0.70, 1.20]),
    ("يُستخدم هذا الوصول", TIED_TAIL, [0.65, 0.80, 1.20]),
    ("نسمح له يسوي", SEQUENTIAL, [0.60, 0.85, 1.20]),
])
def test_encoded_reveal_keeps_the_first_spoken_word_on_the_right(tmp_path: Path, text, timing, times) -> None:
    plan = _plan(tmp_path, text, timing, entry_ms=165)
    ass, lines = _dialogues(plan, tmp_path)
    rows = [_state(line) for line in lines]
    for t in times:
        line = next(line for line, row in zip(lines, rows) if row[0] <= t < row[1])
        frame = _encoded_frame(tmp_path, ass, t, plan)
        assert _first_word_on_the_right(tmp_path, plan, frame, line) < 2.0, (text, t)
    # The completed line is pixel-equal to the cue's logical text shaped as one RTL run.
    # (the last state's own tags, at rest: an entry \move becomes its resting \pos, no fade)
    tags = _state(lines[-1])[2]
    still = re.sub(r"\\move\(-?\d+,-?\d+,(-?\d+),(-?\d+),[^)]*\)", r"\\pos(\1,\2)", tags)
    still = re.sub(r"\\fad\([^)]*\)", "", still)
    renderer = TextRenderer()
    (tmp_path / "whole").mkdir()
    whole, _ = _render_ass(tmp_path / "whole", [renderer._dialogue(0, 1, "Emphasis", still,
                                                                   renderer._directional_text(text, True))],
                           width=plan.width, height=plan.height)
    final = _encoded_frame(tmp_path, ass, times[-1], plan)
    ink = np.abs(whole - 128) > 24
    assert ink.sum() > 1000
    assert float(np.mean(np.abs(final[ink] - whole[ink]))) < 2.0
