"""Forced alignment must survive any canonical-script whitespace formatting.

Root cause covered here: HEXA tokenizes the canonical script on every Unicode whitespace
run (``\\S+``) while WhisperX 3.8.6 starts a new word only after an ASCII space. Sending a
paragraph-formatted script verbatim merged tokens on the aligner side and shifted every
later word (the real ``script=326, aligned=300, match=0.067`` failure).

The fix: an alignment-only ASCII-space token view whose tokens map back to the ORIGINAL
canonical character spans. The canonical script is never modified.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.models import Transcript
from app.shared.errors import HexaError
from app.story.planner import StoryPlanner
from app.transcription.alignment import (
    AlignmentRejectedError,
    detect_script_language,
    prepare_alignment_text,
    word_mapping_diagnostics,
)
from app.transcription.alignment.whisperx import AlignmentPolicy
from tests.support.alignment_fake import audio_stub, fake_aligner, timed_words, whisperx_words

WHITESPACE = {
    "space": " ",
    "tab": "\t",
    "newline": "\n",
    "crlf": "\r\n",
    "cr": "\r",
    "vertical_tab": "\v",
    "form_feed": "\f",
    "nbsp": " ",
    "narrow_nbsp": " ",
    "thin_space": " ",
    "em_space": " ",
    "paragraph": "\n\n",
    "mixed_run": " \t\r\n \n",
}


def _spans_are_verbatim(script: str, prepared) -> bool:
    return all(script[t.char_start:t.char_end] == t.text for t in prepared.tokens)


# ---------------------------------------------------------------- preparation


def test_prepare_alignment_text_keeps_script_and_maps_original_spans() -> None:
    script = "a\n\nb\tc"
    prepared = prepare_alignment_text(script)
    assert prepared.script == script  # canonical text untouched
    assert prepared.text == "a b c"
    assert [(t.text, t.char_start, t.char_end) for t in prepared.tokens] == [
        ("a", 0, 1), ("b", 3, 4), ("c", 5, 6),
    ]
    assert _spans_are_verbatim(script, prepared)


@pytest.mark.parametrize("name", sorted(WHITESPACE))
def test_every_whitespace_separator_yields_the_same_token_sequence(name: str) -> None:
    separator = WHITESPACE[name]
    english = f"hello{separator}world"
    arabic = f"شيئًا أسوأ:{separator}معلومات حساسة"
    assert [t.text for t in prepare_alignment_text(english).tokens] == ["hello", "world"]
    assert prepare_alignment_text(english).text == "hello world"
    assert [t.text for t in prepare_alignment_text(arabic).tokens] == [
        "شيئًا", "أسوأ:", "معلومات", "حساسة",
    ]
    assert _spans_are_verbatim(arabic, prepare_alignment_text(arabic))
    # Semantic equivalence: the aligner sees identical text for every variant.
    assert prepare_alignment_text(arabic).text == "شيئًا أسوأ: معلومات حساسة"


@pytest.mark.parametrize("script", [
    "لكن بعد أشهر، يكتشف الفريق شيئًا أسوأ:\n\nمعلومات حساسة كانت تخرج.",
    "قوي؟\nهنا تبدأ المشكلة.",
    'مو:\n"كيف دخل؟"\nبل:\n"كيف بقي؟"',
    "الإصدار 2.0\nيعمل بشكل مختلف.",
    "hello\nworld", "hello\r\nworld", "hello\tworld", "one:\n\ntwo", "version 2.0\nworks",
    "can't\nstop", "state-linked\ngroup", "word... next",
    "الهاكر يستخدم VPN\nثم يرجع للنظام", "Version 2.0\nيعمل هنا", "API\nواجهة برمجية",
    "Wi-Fi\nشبكة", "أرقام ١٢٣ و 456\tمعًا", "الكلمة المُشَكَّلة\nوالتطويل ـــ هنا",
    "(بين قوسين)\n«اقتباس»؛ ثم؛\nنهاية...", "https://example.com/path\nرابط",
])
def test_formatted_scripts_prepare_to_ascii_separated_tokens(script: str) -> None:
    prepared = prepare_alignment_text(script)
    assert prepared.tokens
    assert " " not in "".join(t.text for t in prepared.tokens)
    assert prepared.text.split(" ") == [t.text for t in prepared.tokens]
    assert whisperx_words(prepared.text) == [t.text for t in prepared.tokens]
    assert _spans_are_verbatim(script, prepared)
    # Language authority stays with the canonical script, not the alignment view.
    assert detect_script_language(prepared.text) == detect_script_language(script)


@pytest.mark.parametrize("script", ["", "   ", "\n\n\t\r\n", "  "])
def test_empty_or_whitespace_only_scripts_prepare_to_nothing(script: str) -> None:
    prepared = prepare_alignment_text(script)
    assert prepared.tokens == () and prepared.text == "" and prepared.script == script


def test_leading_trailing_and_long_whitespace_runs_do_not_move_spans() -> None:
    script = "\n\n  first" + " " * 500 + "\n" * 200 + "last\n"
    prepared = prepare_alignment_text(script)
    assert [t.text for t in prepared.tokens] == ["first", "last"]
    assert prepared.tokens[0].char_start == 4
    assert prepared.tokens[1].char_end == len(script) - 1
    assert prepared.text == "first last"


def test_punctuation_only_script_is_tokenized_but_unsupported_for_alignment() -> None:
    prepared = prepare_alignment_text("... ?? !!")
    assert [t.text for t in prepared.tokens] == ["...", "??", "!!"]
    with pytest.raises(AlignmentRejectedError) as info:
        detect_script_language(prepared.script)
    assert info.value.effective_code == "ALIGNMENT_SCRIPT_UNSUPPORTED"


# ------------------------------------------------------- fake WhisperX round trip


def test_whisperx_receives_ascii_text_and_transcript_keeps_original_spans(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    script = "alpha\n\nbeta\tgamma"
    aligner, fake = fake_aligner(monkeypatch, 3.0)
    transcript = aligner.align(audio_stub(tmp_path), script, 3.0)

    assert fake.received_texts == ["alpha beta gamma"]
    assert [w.text for w in transcript.words] == ["alpha", "beta", "gamma"]
    assert [(w.char_start, w.char_end) for w in transcript.words] == [(0, 5), (7, 11), (12, 17)]
    for word in transcript.words:
        assert script[word.char_start:word.char_end] == word.text
    assert transcript.words[0].start < transcript.words[1].start < transcript.words[2].start


def test_verbatim_formatted_script_would_merge_words_on_the_aligner_side() -> None:
    """Documents the WhisperX 3.8.6 boundary rule the fix compensates for."""
    assert whisperx_words("أسوأ:\n\nمعلومات") == ["أسوأ:\n\nمعلومات"]
    assert whisperx_words("hello\tworld") == ["hello\tworld"]
    assert whisperx_words("hello world") == ["hello", "world"]


def test_transcript_word_text_is_canonical_even_when_aligner_drops_punctuation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    script = "الرصيد المتاح،\nثم البطاقة."
    strip = str.maketrans("", "", "،.")
    aligner, _ = fake_aligner(
        monkeypatch, 2.0, splitter=lambda text: [w.translate(strip) for w in whisperx_words(text)],
    )
    transcript = aligner.align(audio_stub(tmp_path), script, 2.0)
    assert [w.text for w in transcript.words] == ["الرصيد", "المتاح،", "ثم", "البطاقة."]
    assert all(script[w.char_start:w.char_end] == w.text for w in transcript.words)


def test_scene_span_after_paragraph_break_resolves_to_its_own_word_timing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    script = "AAA\n\nBBB"
    aligner, _ = fake_aligner(monkeypatch, 2.0)
    transcript = aligner.align(audio_stub(tmp_path), script, 2.0)
    bbb = transcript.words[1]
    assert (bbb.char_start, bbb.char_end) == (5, 8)  # original span, not "AAA BBB" offset 4
    start, end, narration = StoryPlanner._timing_for_span(transcript, script, 5, 7, None)
    assert (start, end) == (bbb.start, bbb.end) and narration == "BBB"
    # The span of the first token still resolves to the first word only.
    start, end, _ = StoryPlanner._timing_for_span(transcript, script, 0, 2, None)
    assert (start, end) == (transcript.words[0].start, transcript.words[0].end)


# ------------------------------------------------------------ regression 326→300


def _regression_script() -> str:
    """326 canonical tokens, 26 non-space boundaries; the first merge swallows token 22."""
    words = [f"كلمة{index:03d}" for index in range(326)]
    breaks = {23 + 11 * step for step in range(26)}  # before tokens 23, 34, ..., 298
    pieces = [words[0]]
    for index in range(1, 326):
        if index in breaks:
            pieces.append("\n\n" if index % 2 == 0 else "\n")
        else:
            pieces.append(" ")
        pieces.append(words[index])
    return "".join(pieces)


def test_regression_326_tokens_with_26_newline_boundaries() -> None:
    script = _regression_script()
    prepared = prepare_alignment_text(script)
    # BEFORE: the verbatim script gave WhisperX 300 words and a positional cascade.
    merged = whisperx_words(script)
    assert len(prepared.tokens) == 326 and len(merged) == 300
    before = word_mapping_diagnostics(prepared, timed_words(merged, 100.0))
    assert before["aligned_word_count"] == 300
    assert before["match_ratio"] == pytest.approx(22 / 326, abs=0.001)  # 0.067
    assert before["first_mismatch_index"] == 22
    # AFTER: the alignment view keeps all 326 boundaries and every token matches.
    after = word_mapping_diagnostics(prepared, timed_words(whisperx_words(prepared.text), 100.0))
    assert after["alignment_input_token_count"] == 326
    assert after["aligned_word_count"] == 326
    assert after["exact_match_count"] == 326 and after["match_ratio"] == 1.0
    assert after["first_mismatch_index"] is None


def test_regression_script_aligns_end_to_end_without_lowering_the_gate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    script = _regression_script()
    aligner, fake = fake_aligner(monkeypatch, 120.0)
    assert aligner.policy.min_token_match_ratio == 0.98  # not relaxed
    transcript = aligner.align(audio_stub(tmp_path), script, 120.0)
    assert len(transcript.words) == 326
    assert "\n" not in fake.received_texts[0]
    assert all(script[w.char_start:w.char_end] == w.text for w in transcript.words)
    assert transcript.words[-1].text == "كلمة325"


# ------------------------------------------------------------------ fail closed


def _reject(monkeypatch, tmp_path, script, duration, **kwargs) -> AlignmentRejectedError:
    aligner, _ = fake_aligner(monkeypatch, duration, **kwargs)
    with pytest.raises(AlignmentRejectedError) as info:
        aligner.align(audio_stub(tmp_path), script, duration)
    return info.value


def _mismatch_at(position: str):
    def transform(words):
        index = {"beginning": 0, "middle": len(words) // 2, "end": len(words) - 1}[position]
        words[index] = {**words[index], "word": "زائف"}
        return words
    return transform


@pytest.mark.parametrize("position", ["beginning", "middle", "end"])
def test_same_count_but_wrong_token_is_rejected_with_first_mismatch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, position: str,
) -> None:
    script = "\n".join(f"كلمة{i}" for i in range(12))
    error = _reject(monkeypatch, tmp_path, script, 5.0, transform=_mismatch_at(position))
    details = error.details
    assert error.effective_code == "ALIGNMENT_WORD_MAPPING_UNSAFE"
    expected_index = {"beginning": 0, "middle": 6, "end": 11}[position]
    assert details["first_mismatch_index"] == expected_index
    assert details["expected_token"] == f"كلمة{expected_index}"
    assert details["actual_token"] == "زائف"
    assert details["canonical_token_count"] == 12 == details["aligned_word_count"]
    assert details["match_ratio"] == pytest.approx(11 / 12, abs=0.001)
    assert details["whitespace_normalized"] is True and details["language"] == "ar"
    assert len(details["context_before"]["expected"]) <= 3
    assert "كلمة" * 12 not in str(details)  # never the whole script


@pytest.mark.parametrize("change", ["fewer", "more", "empty"])
def test_word_count_mismatch_is_rejected_not_zipped(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, change: str,
) -> None:
    transforms = {
        "fewer": lambda words: words[:-1],
        "more": lambda words: words + [{"word": "extra", "start": 4.5, "end": 4.6}],
        "empty": lambda words: [],
    }
    error = _reject(monkeypatch, tmp_path, "one\ntwo\nthree\nfour", 5.0, transform=transforms[change])
    assert error.effective_code == "ALIGNMENT_WORD_MAPPING_UNSAFE"
    assert error.details["canonical_token_count"] == 4
    assert error.details["aligned_word_count"] == {"fewer": 3, "more": 5, "empty": 0}[change]


@pytest.mark.parametrize("defect", ["missing_start", "missing_end", "non_monotonic", "outside"])
def test_timestamp_defects_stay_rejected(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, defect: str,
) -> None:
    def transform(words):
        if defect == "missing_start":
            words[1] = {"word": words[1]["word"], "end": words[1]["end"]}
        elif defect == "missing_end":
            words[1] = {"word": words[1]["word"], "start": words[1]["start"]}
        elif defect == "non_monotonic":
            words[2] = {**words[2], "start": 0.0, "end": 0.1}
        else:
            words[-1] = {**words[-1], "end": 9.0}
        return words

    error = _reject(monkeypatch, tmp_path, "one\ntwo\nthree\nfour", 5.0, transform=transform)
    assert error.effective_code == "ALIGNMENT_TIMESTAMP_INVALID"
    assert "token_index" in error.details


def test_real_audio_script_mismatch_is_still_rejected_at_the_unchanged_threshold(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Audio that says other words: 0.98 is the production gate and stays fail closed."""
    script = "\n".join(f"word{i}" for i in range(50))

    def transform(words):
        for index in (10, 30):
            words[index] = {**words[index], "word": "different"}
        return words

    error = _reject(monkeypatch, tmp_path, script, 20.0, transform=transform)
    assert error.details["match_ratio"] == 0.96 < AlignmentPolicy().min_token_match_ratio
    assert error.effective_code == "ALIGNMENT_WORD_MAPPING_UNSAFE"


def test_alignment_rejection_is_a_typed_hexa_error() -> None:
    assert issubclass(AlignmentRejectedError, HexaError)
    assert issubclass(AlignmentRejectedError, RuntimeError)
    assert AlignmentRejectedError("x").effective_code == "ALIGNMENT_REJECTED"


def test_strict_service_never_falls_back_when_mapping_is_unsafe(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    from app.transcription.service import TranscriptionService

    aligner, _ = fake_aligner(monkeypatch, 5.0, transform=lambda words: words[:-1])
    service = TranscriptionService(
        model_name="small", forced_aligner=aligner, require_forced_alignment=True,
    )
    monkeypatch.setattr("app.transcription.service.probe_duration", lambda *_: 5.0)
    monkeypatch.setattr(
        service, "_faster_whisper",
        lambda *_: (_ for _ in ()).throw(AssertionError("fallback must not run")),
    )
    with pytest.raises(AlignmentRejectedError) as info:
        service.transcribe(audio_stub(tmp_path), "one\ntwo\nthree")
    assert info.value.effective_code == "ALIGNMENT_WORD_MAPPING_UNSAFE"


def test_transcript_model_round_trip_keeps_original_spans(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    script = "قوي؟\nهنا تبدأ المشكلة."
    aligner, _ = fake_aligner(monkeypatch, 3.0)
    transcript = aligner.align(audio_stub(tmp_path), script, 3.0)
    restored = Transcript.model_validate(transcript.model_dump())
    assert [(w.text, w.char_start, w.char_end) for w in restored.words] == [
        ("قوي؟", 0, 4), ("هنا", 5, 8), ("تبدأ", 9, 13), ("المشكلة.", 14, 22),
    ]
    assert [segment.text for segment in restored.segments] == ["قوي؟", "هنا تبدأ المشكلة."]
