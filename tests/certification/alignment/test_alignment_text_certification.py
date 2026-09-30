"""Certification matrix for the alignment text view (whitespace-independent token map).

Invariants, for every generated script:
  * the alignment token sequence equals the canonical ``\\S+`` token sequence
  * every token is a verbatim slice of the canonical script at its recorded span
  * the text handed to the aligner splits back into exactly those tokens under the
    WhisperX 3.8.6 boundary rule (ASCII space only)
  * a fake WhisperX round trip yields a transcript whose word texts and spans are canonical
  * language detection is unchanged by the view
"""

from __future__ import annotations

import random
import time
from pathlib import Path

import pytest

from app.transcription.alignment import (
    detect_script_language,
    prepare_alignment_text,
    word_mapping_diagnostics,
)
from tests.support.alignment_fake import audio_stub, fake_aligner, timed_words, whisperx_words

SEPARATORS = [
    " ", "\t", "\n", "\r\n", "\r", "\v", "\f", " ", " ", " ", " ", "\n\n",
    " \n", "\n ", "\t\t", "   ", "\r\n\r\n", "  ", " \t\r\n \n",
]
ARABIC_WORDS = (
    "لكن بعد أشهر يكتشف الفريق شيئًا أسوأ معلومات حساسة كانت تخرج من الشبكة الهاكر يستخدم "
    "المنفذ ثم يرجع للنظام قوي هنا تبدأ المشكلة كيف دخل كيف بقي الإصدار يعمل بشكل مختلف "
    "المُشَكَّلة التطويل مفتاح البوابة الحارس الهوية المسروقة الرصيد البطاقة الرسالة المزيفة"
).split()
ENGLISH_WORDS = (
    "the team discovers something worse sensitive information was leaving the network "
    "attacker uses the gateway then returns version works differently can't stop state-linked "
    "group word next available balance card identity message fake strong here begins problem"
).split()
PUNCTUATION = ["،", ".", "؟", ":", "؛", "...", "!", ",", "?", ";", "-", "—"]
WRAPS = [("«", "»"), ('"', '"'), ("(", ")"), ("[", "]"), ("'", "'")]
DIGITS = ["2.0", "١٢٣", "456", "3.5%", "10x", "2026", "٢٠٢٦", "1,000"]
ABBREVIATIONS = ["VPN", "API", "Wi-Fi", "HTTP", "e.g.", "U.S.", "ID", "OK"]
PUNCTUATION_EDGE_TOKENS = [
    "أسوأ:", "معلومات،", "نهاية.", "قوي؟", "ثم؛", "انتظر...", "كلمة!", "(بين", "قوسين)", "«اقتباس»",
    '"quoted"', "state-linked", "can't", "word...", "2.0", "٣.٥", "e.g.", "U.S.", "3:45", "a-b-c",
    "hello,", "world.", "wait?!", "..", "—", "ـــكلمةـــ", "مُشَكَّل", "1,000.00", "50%", "#tag",
    "@user", "x/y", "a|b", "«hi»,", "(ok).", "[note]:", "end…", "؟!", "،،", ".", "?",
]


def _tokens(script: str) -> list[str]:
    return [token.text for token in prepare_alignment_text(script).tokens]


def _check(script: str) -> None:
    prepared = prepare_alignment_text(script)
    expected = script.split()  # str.split() = Unicode whitespace runs = \S+ tokens
    assert [t.text for t in prepared.tokens] == expected
    assert prepared.script is script
    assert all(script[t.char_start:t.char_end] == t.text for t in prepared.tokens)
    starts = [t.char_start for t in prepared.tokens]
    assert starts == sorted(starts) and len(set(starts)) == len(starts)
    assert prepared.text == " ".join(expected)
    assert whisperx_words(prepared.text) == expected
    if any(character.isalpha() for character in script):
        assert detect_script_language(prepared.text) == detect_script_language(script)


def _formatted(rng: random.Random, words: list[str]) -> str:
    return "".join(
        word + (rng.choice(SEPARATORS) if index < len(words) - 1 else "")
        for index, word in enumerate(words)
    )


def _arabic_document(rng: random.Random) -> list[str]:
    words = []
    for _ in range(rng.randint(2, 6)):  # paragraphs
        for _ in range(rng.randint(3, 25)):
            word = rng.choice(ARABIC_WORDS)
            roll = rng.random()
            if roll < 0.10:
                word = rng.choice(DIGITS)
            elif roll < 0.18:
                word = rng.choice(ABBREVIATIONS)
            if rng.random() < 0.25:
                word += rng.choice(PUNCTUATION)
            if rng.random() < 0.06:
                left, right = rng.choice(WRAPS)
                word = f"{left}{word}{right}"
            words.append(word)
    return words


def _english_document(rng: random.Random) -> list[str]:
    words = []
    for _ in range(rng.randint(5, 80)):
        word = rng.choice(ENGLISH_WORDS + DIGITS[:3] + ABBREVIATIONS)
        if rng.random() < 0.2:
            word += rng.choice([".", ",", "?", "!", ":", ";", "..."])
        words.append(word)
    return words


def _mixed_document(rng: random.Random) -> list[str]:
    words = []
    for _ in range(rng.randint(5, 60)):
        pool = ARABIC_WORDS if rng.random() < 0.65 else ENGLISH_WORDS + ABBREVIATIONS + DIGITS
        word = rng.choice(pool)
        if rng.random() < 0.2:
            word += rng.choice(PUNCTUATION)
        words.append(word)
    return words


# --------------------------------------------------------- 1000 randomized whitespace


@pytest.mark.parametrize("seed", range(1000))
def test_randomized_whitespace_never_changes_tokens_or_spans(seed: int) -> None:
    rng = random.Random(seed)
    base = [rng.choice(ARABIC_WORDS + ENGLISH_WORDS + PUNCTUATION_EDGE_TOKENS)
            for _ in range(rng.randint(1, 40))]
    script = _formatted(rng, base)
    if rng.random() < 0.3:
        script = rng.choice(SEPARATORS) + script
    if rng.random() < 0.3:
        script += rng.choice(SEPARATORS)
    _check(script)
    assert _tokens(script) == base
    # Same words, different formatting: identical alignment text.
    assert prepare_alignment_text(_formatted(random.Random(seed + 1), base)).text == " ".join(base)


# ------------------------------------------------- Arabic / English / mixed documents


@pytest.mark.parametrize("seed", range(300))
def test_arabic_formatting_variants(seed: int) -> None:
    rng = random.Random(10_000 + seed)
    words = _arabic_document(rng)
    script = _formatted(rng, words)
    _check(script)
    assert detect_script_language(script) == "ar"
    assert _tokens(script) == words


@pytest.mark.parametrize("seed", range(200))
def test_english_formatting_variants(seed: int) -> None:
    rng = random.Random(20_000 + seed)
    words = _english_document(rng)
    script = _formatted(rng, words)
    _check(script)
    assert detect_script_language(script) == "en"
    assert _tokens(script) == words


@pytest.mark.parametrize("seed", range(200))
def test_mixed_language_formatting_variants(seed: int) -> None:
    rng = random.Random(30_000 + seed)
    words = _mixed_document(rng)
    script = _formatted(rng, words)
    _check(script)
    assert _tokens(script) == words


# ------------------------------------------------------------ punctuation edge cases


@pytest.mark.parametrize("token", PUNCTUATION_EDGE_TOKENS)
@pytest.mark.parametrize("separator", ["\n", "\n\n", "\t", " "])
def test_punctuation_edge_tokens_survive_every_boundary(token: str, separator: str) -> None:
    script = f"قبل{separator}{token}{separator}بعد"
    _check(script)
    assert _tokens(script) == ["قبل", token, "بعد"]


# ---------------------------------------------------------------- fake round trips


@pytest.mark.parametrize("seed", range(120))
def test_fake_whisperx_round_trip_keeps_canonical_words_and_spans(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, seed: int,
) -> None:
    rng = random.Random(40_000 + seed)
    words = [_arabic_document, _english_document, _mixed_document][seed % 3](rng)
    script = _formatted(rng, words)
    duration = float(len(words)) * 0.4 + 1.0
    aligner, fake = fake_aligner(monkeypatch, duration)
    transcript = aligner.align(audio_stub(tmp_path), script, duration)
    assert fake.received_texts == [" ".join(words)]
    assert [w.text for w in transcript.words] == words
    assert all(script[w.char_start:w.char_end] == w.text for w in transcript.words)
    assert all(a.end <= b.start + 1e-9 for a, b in zip(transcript.words, transcript.words[1:]))
    # Segments are canonical phrase slices in script order built from those same words.
    canonical = {(w.char_start, w.char_end) for w in transcript.words}
    assert all((w.char_start, w.char_end) in canonical for s in transcript.segments for w in s.words)
    assert all(script[s.char_start:s.char_end].strip() == s.text for s in transcript.segments)
    segment_starts = [s.char_start for s in transcript.segments]
    assert segment_starts == sorted(segment_starts)
    assert {w.char_start for s in transcript.segments for w in s.words} == {
        w.char_start for w in transcript.words
    }


# ------------------------------------------------------------------ size matrix


SIZES = (1, 10, 50, 100, 326, 500, 1000, 5000)
_TIMINGS: dict[int, float] = {}


@pytest.mark.parametrize("size", SIZES)
def test_long_scripts_prepare_in_linear_time(size: int) -> None:
    rng = random.Random(size)
    words = [rng.choice(ARABIC_WORDS + ENGLISH_WORDS) for _ in range(size)]
    script = _formatted(rng, words)
    started = time.perf_counter()
    prepared = prepare_alignment_text(script)
    elapsed = time.perf_counter() - started
    _TIMINGS[size] = elapsed
    assert len(prepared.tokens) == size
    assert whisperx_words(prepared.text) == words
    assert all(script[t.char_start:t.char_end] == t.text for t in prepared.tokens)
    assert elapsed < 0.05 + size * 2e-5  # ~O(n): 5000 tokens well under 150 ms
    report = word_mapping_diagnostics(prepared, timed_words(whisperx_words(prepared.text), size * 0.4))
    assert report["match_ratio"] == 1.0 and report["first_mismatch_index"] is None


def test_size_matrix_scales_linearly() -> None:
    assert set(SIZES) <= set(_TIMINGS)
    per_token_small = _TIMINGS[100] / 100
    per_token_large = _TIMINGS[5000] / 5000
    # Allow noise, but rule out quadratic behaviour.
    assert per_token_large < per_token_small * 8 + 1e-6
