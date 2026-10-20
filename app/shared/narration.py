"""Narration structure shared by Boundary (idea boards) and Motion (idea climax)."""

from __future__ import annotations

SENTENCE_END = frozenset(".!?؟…")
_CLOSERS = "\"'»)]}”’ "


def continues_sentence(narration: str | None) -> bool:
    """True when a beat's narration stops mid-sentence: the next picture is the same idea."""
    text = (narration or "").strip().rstrip(_CLOSERS)
    return bool(text) and any(char.isalpha() for char in text) and text[-1] not in SENTENCE_END
