from __future__ import annotations

from dataclasses import dataclass

from app.models import Transcript, TranscriptWord
from app.text.semantic import KeywordCandidate, KeywordToken


@dataclass(frozen=True, slots=True)
class TimedToken:
    display_text: str
    source_char_start: int
    source_char_end: int
    spoken_start: float
    spoken_end: float


@dataclass(frozen=True, slots=True)
class TimedKeyword:
    candidate: KeywordCandidate
    spoken_start: float
    spoken_end: float
    emphasis_time: float
    tokens: tuple[TimedToken, ...] = ()


class TextTimingPlanner:
    """Map canonical-script spans to real forced-alignment word timestamps.

    Display text is allowed to be normalized or compressed (for example ``ألف`` ->
    ``1000``), so timing never looks up the rendered string. Every cue/token carries a
    source character span and that source span is resolved against forced-aligned words.
    """

    REQUIRED_TIMING_SOURCE = "forced_alignment"

    def align(self, candidate: KeywordCandidate, transcript: Transcript) -> TimedKeyword | None:
        if transcript.timing_source != self.REQUIRED_TIMING_SOURCE:
            return None
        words = self._words_for_span(
            transcript,
            candidate.source_char_start,
            candidate.source_char_end,
        )
        if not words:
            return None

        spoken_start = words[0].start
        spoken_end = words[-1].end
        if spoken_end <= spoken_start:
            return None

        token_anchors = candidate.tokens or (
            KeywordToken(
                display_text=candidate.display_text,
                source_char_start=candidate.source_char_start,
                source_char_end=candidate.source_char_end,
            ),
        )
        timed_tokens: list[TimedToken] = []
        for token in token_anchors:
            token_words = self._words_for_span(
                transcript,
                token.source_char_start,
                token.source_char_end,
            )
            if not token_words:
                return None
            token_start = token_words[0].start
            token_end = token_words[-1].end
            if token_end <= token_start:
                return None
            timed_tokens.append(TimedToken(
                display_text=token.display_text,
                source_char_start=token.source_char_start,
                source_char_end=token.source_char_end,
                spoken_start=token_start,
                spoken_end=token_end,
            ))

        # Source order, not display-string matching, is authoritative. This keeps repeated
        # words and transformed numeric text deterministic.
        timed_tokens.sort(key=lambda row: (row.source_char_start, row.source_char_end))
        emphasis_token = max(
            timed_tokens,
            key=lambda row: (
                any(char.isdigit() for char in row.display_text),
                len(row.display_text.strip()),
                -row.spoken_start,
            ),
        )
        emphasis_time = min(spoken_end, max(spoken_start, emphasis_token.spoken_start))
        return TimedKeyword(
            candidate=candidate,
            spoken_start=spoken_start,
            spoken_end=spoken_end,
            emphasis_time=emphasis_time,
            tokens=tuple(timed_tokens),
        )

    @staticmethod
    def _words_for_span(
        transcript: Transcript,
        source_char_start: int,
        source_char_end: int,
    ) -> list[TranscriptWord]:
        words = [
            word
            for word in transcript.words
            if word.char_start is not None
            and word.char_end is not None
            and word.char_end > source_char_start
            and word.char_start < source_char_end
        ]
        words.sort(key=lambda word: (word.start, word.end, word.char_start or 0))
        return words
