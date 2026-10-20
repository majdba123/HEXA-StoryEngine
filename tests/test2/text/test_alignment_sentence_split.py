"""Forced alignment survives author punctuation (2026-10-20 Gray Hat field failure).

The production Gray Hat package said "أوصل لغير مكان!!," and the render stopped:
``forced alignment word mapping is unsafe (script=225, aligned=226, match=0.662)``.
WhisperX groups words per Punkt sentence and Punkt broke the sentence between the two
"!", so one script token came back as two words and every later word shifted. The
repair reproduces WhisperX's grouping exactly and rejoins only the pieces it predicts;
the one-to-one gate still judges everything, so no timing is ever guessed.
"""
from __future__ import annotations

import pytest

from app.transcription.alignment import AlignmentRejectedError, WhisperXForcedAligner
from app.transcription.alignment.prepared_text import prepare_alignment_text
from app.transcription.alignment.whisperx import AlignmentPolicy
from app.transcription.alignment.word_repair import rejoin_split_words, whisperx_word_pieces

FIELD = "خلني أشوف إذا أقدر أوصل لغير مكان!!,\nوبدأت تفتح صفحات ثانية، فكرة الهاكر الرمادي .\nهو غالبًا مو داخل"


def _break_inside(text: str, token: str, after: str) -> list[tuple[int, int]]:
    """Sentence spans with one Punkt break inside ``token``, right after ``after``."""
    cut = text.index(token) + token.index(after) + len(after)
    return [(0, cut), (cut, len(text))]


def _timed(texts: list[str]) -> list[dict]:
    return [{"word": text, "start": 0.1 + 0.3 * n, "end": 0.35 + 0.3 * n, "score": 0.9}
            for n, text in enumerate(texts)]


def test_whisperx_grouping_is_reproduced_for_a_break_inside_a_token() -> None:
    prepared = prepare_alignment_text(FIELD)
    spans = _break_inside(prepared.text, "مكان!!,", "مكان!")
    pieces = [text for _, text in whisperx_word_pieces(prepared.text, spans)]
    # WhisperX's inclusive sentence end hands the second "!" to both sides.
    assert pieces[6:8] == ["مكان!!", "!,"]
    assert len(pieces) == len(prepared.tokens) + 1


def test_split_token_is_rejoined_with_its_full_timing_and_nothing_else_moves() -> None:
    prepared = prepare_alignment_text(FIELD)
    spans = _break_inside(prepared.text, "مكان!!,", "مكان!")
    raw = _timed([text for _, text in whisperx_word_pieces(prepared.text, spans)])
    aligner = WhisperXForcedAligner()
    transcript = aligner._build_transcript(prepared=prepared, language="ar", duration=10.0,
                                           raw_words=raw, sentence_spans=spans)
    assert [word.text for word in transcript.words] == [token.text for token in prepared.tokens]
    split = transcript.words[6]
    assert split.text == "مكان!!," and split.start == pytest.approx(raw[6]["start"])
    assert split.end == pytest.approx(raw[7]["end"])
    assert [(w.start, w.end) for w in transcript.words[:6]] == [(r["start"], r["end"]) for r in raw[:6]]
    assert [(w.start, w.end) for w in transcript.words[7:]] == [(r["start"], r["end"]) for r in raw[8:]]
    assert [repair.token for repair in aligner.word_repairs] == ["مكان!!,"]


def test_without_the_repair_the_field_failure_is_reproduced() -> None:
    prepared = prepare_alignment_text(FIELD)
    spans = _break_inside(prepared.text, "مكان!!,", "مكان!")
    raw = _timed([text for _, text in whisperx_word_pieces(prepared.text, spans)])
    with pytest.raises(AlignmentRejectedError) as caught:
        WhisperXForcedAligner(policy=AlignmentPolicy(salvage=False))._build_transcript(
            prepared=prepared, language="ar", duration=10.0, raw_words=raw)
    assert caught.value.details["code"] == "ALIGNMENT_WORD_MAPPING_UNSAFE"
    assert caught.value.details["aligned_word_count"] == len(prepared.tokens) + 1


def test_unsplit_words_are_returned_as_the_same_objects() -> None:
    prepared = prepare_alignment_text(FIELD)
    raw = _timed([token.text for token in prepared.tokens])
    words, repairs = rejoin_split_words(prepared, raw, [(0, len(prepared.text))])
    assert repairs == [] and all(a is b for a, b in zip(words, raw)) and len(words) == len(raw)


def test_words_that_disagree_with_the_prediction_are_never_regrouped(monkeypatch) -> None:
    monkeypatch.setattr("app.transcription.alignment.whisperx.ALIGNMENT_SALVAGE", False)  # strict contract
    prepared = prepare_alignment_text(FIELD)
    spans = _break_inside(prepared.text, "مكان!!,", "مكان!")
    pieces = [text for _, text in whisperx_word_pieces(prepared.text, spans)]
    raw = _timed(pieces[:3] + ["غلط"] + pieces[4:])
    words, repairs = rejoin_split_words(prepared, raw, spans)
    assert repairs == [] and len(words) == len(raw)
    with pytest.raises(AlignmentRejectedError):
        WhisperXForcedAligner()._build_transcript(prepared=prepared, language="ar", duration=10.0,
                                                  raw_words=raw, sentence_spans=spans)


def test_punctuation_only_tokens_returned_verbatim_count_as_matches() -> None:
    script = "أولًا . ثم - بعدها ! أخيرًا ؟ انتهى …"
    prepared = prepare_alignment_text(script)
    transcript = WhisperXForcedAligner()._build_transcript(
        prepared=prepared, language="ar", duration=10.0, raw_words=_timed(script.split(" ")))
    assert [word.text for word in transcript.words] == script.split(" ")


# ------------------------------------------------- the installed WhisperX alignment code

def _runtime_or_skip():
    pytest.importorskip("whisperx.alignment")
    nltk = pytest.importorskip("nltk")
    try:
        nltk.data.find("tokenizers/punkt_tab/english")
    except LookupError:
        pytest.skip("Punkt data not installed")
    from tests.support import whisperx_runtime

    return whisperx_runtime


def test_installed_whisperx_splits_the_field_token_and_the_aligner_rejoins_it() -> None:
    runtime = _runtime_or_skip()
    prepared = prepare_alignment_text(FIELD)
    assert len(runtime.raw_runtime_words(FIELD)) == len(prepared.tokens) + 1   # WhisperX itself
    transcript = runtime.runtime_align(FIELD)
    assert [word.text for word in transcript.words] == [token.text for token in prepared.tokens]


PATTERNS = [
    "مكان!!,", "كذا!!!", "ليش?!", "معقول؟!", "طيب!؟", "شو؟؟", "وبعدين...", "يعني..", "خلص…", "انتهى!.",
    "صح?.", "ايوا.,", "لا!,", "شو?,", "خلص.!", "يلا!!،", "ليش؟!،", "(هنا.)", "(اوعى!)", "(ليش؟)",
    'قال!"', 'قال."', "«خلص!»", "«انتهى.»", "'لا!'", "'اوكي.'", "وبعدين?!..", "ليش!!!؟",
    ". هو", "! هي", "؟ هم", "، كمان", "- بعدين", "– كمان", "— هيك", "... وبعدين", "!! يا", "?! مين",
    ": هي", "; كمان", "» خلص", "« قال", "* ملاحظة", "Wi-Fi", "e.g.", "U.S.A.", "3.5%", "www.site.com",
    "AI.", "HEXA!!", "#أمن", "@hexa", "١٢٣.", "Mr. Smith", "i.e., هيك",
]


@pytest.mark.parametrize("pattern", PATTERNS)
def test_installed_whisperx_one_word_per_token_for_author_punctuation(pattern: str) -> None:
    runtime = _runtime_or_skip()
    script = f"الهاكر يفتح الملف {pattern} وبعدها يشوف البيانات. ثم يكمل الشغل!! ويخلص."
    prepared = prepare_alignment_text(script)
    transcript = runtime.runtime_align(script)
    assert [word.text for word in transcript.words] == [token.text for token in prepared.tokens]
    assert all(b.start + 0.08 >= a.end for a, b in zip(transcript.words, transcript.words[1:]))
