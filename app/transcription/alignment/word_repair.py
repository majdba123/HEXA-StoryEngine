"""Rejoin script tokens that WhisperX returned as several words.

WhisperX (3.8.x) groups its aligned characters into words *per Punkt sentence*: for every
sentence span it takes the characters ``start <= index <= end`` (inclusive end) and emits
one word per word index found there. Punkt may place a sentence break inside one
whitespace token when sentence-ending punctuation is followed by more punctuation
(``"مكان!!,"``, ``"كذا؟!"``, ``'قال!"'``, ``"هنا.)"``). That token then comes back as several
words (the character at each break given to both sides) and every later word would shift
by one. The CTC character timing itself is unaffected: only the grouping is.

The grouping is a pure function of the alignment text and the sentence spans, so
``whisperx_word_pieces`` reproduces it exactly. ``rejoin_split_words`` merges the aligner's
words back into one word per token ONLY when the aligner's word texts equal that
prediction verbatim; otherwise the words pass through untouched for the one-to-one gate
to judge. A script with no split token yields the aligner's words unchanged (same
objects, same timings).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from app.transcription.alignment.prepared_text import PreparedAlignmentText


@dataclass(frozen=True, slots=True)
class WordRepair:
    token_index: int
    token: str
    pieces: tuple[str, ...]


def whisperx_word_pieces(text: str, sentence_spans: Sequence[tuple[int, int]]) -> list[tuple[int, str]]:
    """``(word index, word text)`` in the order WhisperX emits them for ``text``.

    Mirrors ``whisperx.alignment.align``: a word index advances after every character
    followed by an ASCII space; each sentence takes ``text[start..end]`` inclusive; a
    word's text is its characters joined and stripped, and empty words are skipped.
    """
    word_of: list[int] = []
    word = 0
    for index in range(len(text)):
        word_of.append(word)
        if index == len(text) - 1 or text[index + 1] == " ":
            word += 1
    pieces: list[tuple[int, str]] = []
    for start, end in sentence_spans:
        chars = range(max(0, start), min(end, len(text) - 1) + 1)
        for word_index in dict.fromkeys(word_of[index] for index in chars):
            piece = "".join(text[index] for index in chars if word_of[index] == word_index).strip()
            if piece:
                pieces.append((word_index, piece))
    return pieces


def rejoin_split_words(
    prepared: PreparedAlignmentText,
    raw_words: Sequence[dict[str, Any]],
    sentence_spans: Sequence[tuple[int, int]],
) -> tuple[list[dict[str, Any]], list[WordRepair]]:
    """One aligner word per script token where WhisperX provably split a token.

    The prepared text joins tokens with single spaces, so WhisperX's word index IS the
    token index. Words are regrouped only when their texts match the predicted pieces
    exactly; any disagreement leaves ``raw_words`` as they are.
    """
    predicted = whisperx_word_pieces(prepared.text, sentence_spans)
    if len(predicted) == len(prepared.tokens) or len(predicted) != len(raw_words):
        return list(raw_words), []
    if any(str(raw.get("word") or "") != piece for raw, (_, piece) in zip(raw_words, predicted)):
        return list(raw_words), []
    if [index for index, _ in predicted] != sorted(index for index, _ in predicted):
        return list(raw_words), []
    groups: dict[int, list[dict[str, Any]]] = {}
    for raw, (index, _) in zip(raw_words, predicted):
        groups.setdefault(index, []).append(raw)
    if sorted(groups) != list(range(len(prepared.tokens))):
        return list(raw_words), []
    words: list[dict[str, Any]] = []
    repairs: list[WordRepair] = []
    for index, group in sorted(groups.items()):
        if len(group) == 1:
            words.append(group[0])
            continue
        token = prepared.tokens[index].text
        words.append(_merged(token, group))
        repairs.append(WordRepair(index, token, tuple(str(raw.get("word") or "") for raw in group)))
    return words, repairs


def _merged(token: str, group: Sequence[dict[str, Any]]) -> dict[str, Any]:
    starts = [value for word in group if (value := _number(word.get("start"))) is not None]
    ends = [value for word in group if (value := _number(word.get("end"))) is not None]
    scores = [value for word in group if (value := _number(word.get("score"))) is not None]
    merged: dict[str, Any] = {"word": token}
    if starts:
        merged["start"] = min(starts)
    if ends:
        merged["end"] = max(ends)
    if scores:
        merged["score"] = round(sum(scores) / len(scores), 3)
    return merged


def _number(value: Any) -> float | None:
    try:
        number = float(value) if value is not None else None
    except (TypeError, ValueError):
        return None
    return None if number is None or number != number else number
