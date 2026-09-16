from __future__ import annotations

import re
from dataclasses import dataclass

from app.models import StoryBeat, Transcript, TranscriptWord

_TOKEN_EDGE_RE = re.compile(r"^[\W_]+|[\W_]+$", re.UNICODE)
_DIGIT_RE = re.compile(r"[0-9٠-٩]")

_ARABIC_STOPWORDS = frozenset({
    "في", "من", "على", "إلى", "الى", "عن", "مع", "هذا", "هذه", "ذلك", "تلك",
    "هو", "هي", "هم", "كما", "لكن", "او", "أو", "ثم", "قد", "كان", "كانت",
    "يكون", "تكون", "إذا", "اذا", "كل", "أي", "اي", "ما", "لا", "لم", "لن",
    "و", "ف", "ب", "ل", "التي", "الذي", "عند", "عندما", "بعد", "قبل", "فقط",
})
_ENGLISH_STOPWORDS = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "but", "by", "for", "from",
    "has", "have", "in", "is", "it", "of", "on", "or", "that", "the", "this",
    "to", "was", "were", "will", "with", "you", "your",
})
_CURRENCY_TOKENS = frozenset({
    "ريال", "ريالاً", "ريالا", "ر.س", "sar", "usd", "eur", "دولار", "دولاراً",
    "دولارا", "يورو", "£", "$", "€",
})
_IMPORTANCE_TERMS = frozenset({
    "الرصيد", "المتاح", "محجوز", "محجوزة", "الحد", "اليومي", "رفض", "مرفوض",
    "رسوم", "ضريبة", "شحن", "خصم", "مجاني", "متاح", "تنبيه", "خطأ", "نجاح",
    "balance", "available", "limit", "daily", "reserved", "fee", "tax", "shipping",
    "discount", "free", "warning", "error", "success",
})


@dataclass(frozen=True, slots=True)
class KeywordCandidate:
    display_text: str
    semantic_type: str
    source_char_start: int
    source_char_end: int
    score: float


class TextSemanticSelector:
    """Select a small deterministic set of on-screen keyword candidates.

    The selector intentionally does not own timing or visual styling. It only chooses
    concise phrases whose source characters are traceable back to the canonical script.
    """

    def __init__(self, *, max_keywords_per_beat: int = 2, max_display_chars: int = 24) -> None:
        self.max_keywords_per_beat = max(1, max_keywords_per_beat)
        self.max_display_chars = max(8, max_display_chars)

    def select(self, beat: StoryBeat, transcript: Transcript) -> list[KeywordCandidate]:
        words = self._aligned_words_for_beat(beat, transcript)
        if not words:
            return []

        candidates = self._number_candidates(words)
        candidates.extend(self._semantic_candidates(words, beat))

        deduped: dict[str, KeywordCandidate] = {}
        for candidate in candidates:
            key = self._normalize(candidate.display_text)
            if not key:
                continue
            current = deduped.get(key)
            if current is None or candidate.score > current.score:
                deduped[key] = candidate

        budget = self._budget(beat)
        ranked = sorted(
            deduped.values(),
            key=lambda item: (-item.score, item.source_char_start, item.display_text),
        )
        selected: list[KeywordCandidate] = []
        for candidate in ranked:
            if any(self._overlaps(candidate, existing) for existing in selected):
                continue
            selected.append(candidate)
            if len(selected) >= budget:
                break
        return sorted(selected, key=lambda item: item.source_char_start)

    def _number_candidates(self, words: list[TranscriptWord]) -> list[KeywordCandidate]:
        output: list[KeywordCandidate] = []
        for index, word in enumerate(words):
            cleaned = self._clean(word.text)
            if not cleaned or not _DIGIT_RE.search(cleaned):
                continue
            phrase = [word]
            cursor = index + 1
            if cursor < len(words) and self._clean(words[cursor].text).lower() in _CURRENCY_TOKENS:
                phrase.append(words[cursor])
                cursor += 1
            if cursor < len(words):
                next_clean = self._clean(words[cursor].text).lower()
                if next_clean in _IMPORTANCE_TERMS:
                    phrase.append(words[cursor])
            candidate = self._candidate_from_words(
                phrase,
                semantic_type="amount" if len(phrase) > 1 else "number",
                score=1.00 + (0.12 if len(phrase) > 1 else 0.0),
            )
            if candidate:
                output.append(candidate)
        return output

    def _semantic_candidates(
        self,
        words: list[TranscriptWord],
        beat: StoryBeat,
    ) -> list[KeywordCandidate]:
        output: list[KeywordCandidate] = []
        action_bonus = 0.12 if beat.action in {"EMPHASIZE", "RESULT", "HANDOFF"} else 0.0
        for index, word in enumerate(words):
            cleaned = self._clean(word.text)
            if not self._is_content_word(cleaned):
                continue
            normalized = cleaned.lower()
            score = 0.52 + action_bonus
            semantic_type = "keyword"
            if normalized in _IMPORTANCE_TERMS:
                score += 0.24
                semantic_type = "emphasis"

            phrase = [word]
            if index + 1 < len(words):
                next_clean = self._clean(words[index + 1].text)
                combined = f"{cleaned} {next_clean}".strip()
                if self._is_content_word(next_clean) and len(combined) <= self.max_display_chars:
                    phrase.append(words[index + 1])
                    score += 0.05
            candidate = self._candidate_from_words(phrase, semantic_type, score)
            if candidate:
                output.append(candidate)
        return output

    def _candidate_from_words(
        self,
        words: list[TranscriptWord],
        semantic_type: str,
        score: float,
    ) -> KeywordCandidate | None:
        if not words:
            return None
        first = words[0]
        last = words[-1]
        if first.char_start is None or last.char_end is None:
            return None
        display = " ".join(self._clean(word.text) for word in words).strip()
        if not display or len(display) > self.max_display_chars:
            return None
        if semantic_type == "amount" and any(
            self._clean(word.text).lower() in {"محجوز", "محجوزة", "reserved"}
            for word in words
        ):
            semantic_type = "warning_amount"
        return KeywordCandidate(
            display_text=display,
            semantic_type=semantic_type,
            source_char_start=first.char_start,
            source_char_end=last.char_end,
            score=score,
        )

    @staticmethod
    def _aligned_words_for_beat(beat: StoryBeat, transcript: Transcript) -> list[TranscriptWord]:
        audio_start = beat.audio_start if beat.audio_start is not None else beat.start
        audio_end = beat.audio_end if beat.audio_end is not None else beat.end
        return [
            word
            for word in transcript.words
            if word.char_start is not None
            and word.char_end is not None
            and word.end > audio_start
            and word.start < audio_end
        ]

    def _budget(self, beat: StoryBeat) -> int:
        audio_start = beat.audio_start if beat.audio_start is not None else beat.start
        audio_end = beat.audio_end if beat.audio_end is not None else beat.end
        duration = max(0.0, audio_end - audio_start)
        if duration < 1.5:
            return 1
        return min(2, self.max_keywords_per_beat)

    @staticmethod
    def _is_content_word(value: str) -> bool:
        normalized = value.lower()
        if not normalized or len(normalized) < 3 or _DIGIT_RE.search(normalized):
            return False
        if normalized in _ARABIC_STOPWORDS or normalized in _ENGLISH_STOPWORDS:
            return False
        return any(char.isalpha() for char in normalized)

    @staticmethod
    def _clean(value: str) -> str:
        return _TOKEN_EDGE_RE.sub("", value.strip())

    @classmethod
    def _normalize(cls, value: str) -> str:
        return " ".join(cls._clean(value).lower().split())

    @staticmethod
    def _overlaps(left: KeywordCandidate, right: KeywordCandidate) -> bool:
        return (
            left.source_char_start < right.source_char_end
            and left.source_char_end > right.source_char_start
        )
