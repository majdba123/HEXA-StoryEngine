from __future__ import annotations

from dataclasses import dataclass

from app.models import Transcript
from app.text.semantic import KeywordCandidate


@dataclass(frozen=True, slots=True)
class TimedKeyword:
    candidate: KeywordCandidate
    spoken_start: float
    spoken_end: float
    emphasis_time: float


class TextTimingPlanner:
    """Map canonical-script spans to real forced-alignment word timestamps."""

    REQUIRED_TIMING_SOURCE = "forced_alignment"

    def align(self, candidate: KeywordCandidate, transcript: Transcript) -> TimedKeyword | None:
        if transcript.timing_source != self.REQUIRED_TIMING_SOURCE:
            return None
        words = [
            word
            for word in transcript.words
            if word.char_start is not None
            and word.char_end is not None
            and word.char_end > candidate.source_char_start
            and word.char_start < candidate.source_char_end
        ]
        if not words:
            return None
        words.sort(key=lambda word: (word.start, word.end, word.char_start or 0))
        spoken_start = words[0].start
        spoken_end = words[-1].end
        if spoken_end <= spoken_start:
            return None

        emphasis_word = max(
            words,
            key=lambda word: (
                any(char.isdigit() for char in word.text),
                len(word.text.strip()),
                -word.start,
            ),
        )
        emphasis_time = min(spoken_end, max(spoken_start, emphasis_word.start))
        return TimedKeyword(
            candidate=candidate,
            spoken_start=spoken_start,
            spoken_end=spoken_end,
            emphasis_time=emphasis_time,
        )
