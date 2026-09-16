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
    "إن", "ان", "إنك", "انك", "لك", "منها", "له", "لها", "اللي", "هنا", "كذا",
    "خلال", "بعدها", "وحتى", "حتى",
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
_ARABIC_NUMBER_WORDS = frozenset({
    "صفر", "واحد", "واحدة", "اثنان", "اثنين", "اثنتان", "اثنتين", "ثلاثة", "ثلاث",
    "أربعة", "اربعة", "خمس", "خمسة", "ست", "ستة", "سبع", "سبعة", "ثمان", "ثمانية",
    "تسع", "تسعة", "عشر", "عشرة", "عشرين", "ثلاثين", "أربعين", "اربعين", "خمسين",
    "ستين", "سبعين", "ثمانين", "تسعين", "مئة", "مائة", "مئتين", "مائتين", "ثلاثمئة",
    "ثلاثمائة", "أربعمئة", "اربعمئة", "أربعمائة", "اربعمائة", "خمسمئة", "خمسمائة",
    "ستمئة", "ستمائة", "سبعمئة", "سبعمائة", "ثمانمئة", "ثمانمائة", "تسعمئة", "تسعمائة",
    "ألف", "الف", "ألفين", "الفين", "آلاف", "الاف", "مليون", "مليونين", "ملايين",
})
_ARABIC_NUMBER_VALUES = {
    "صفر": 0, "واحد": 1, "واحدة": 1, "اثنان": 2, "اثنين": 2, "اثنتان": 2, "اثنتين": 2,
    "ثلاث": 3, "ثلاثة": 3, "أربع": 4, "اربعة": 4, "أربعة": 4, "خمس": 5, "خمسة": 5,
    "ست": 6, "ستة": 6, "سبع": 7, "سبعة": 7, "ثمان": 8, "ثمانية": 8, "تسع": 9, "تسعة": 9,
    "عشر": 10, "عشرة": 10, "عشرين": 20, "ثلاثين": 30, "أربعين": 40, "اربعين": 40,
    "خمسين": 50, "ستين": 60, "سبعين": 70, "ثمانين": 80, "تسعين": 90,
    "مئة": 100, "مائة": 100, "مئتين": 200, "مائتين": 200,
    "ثلاثمئة": 300, "ثلاثمائة": 300, "أربعمئة": 400, "اربعمئة": 400,
    "أربعمائة": 400, "اربعمائة": 400, "خمسمئة": 500, "خمسمائة": 500,
    "ستمئة": 600, "ستمائة": 600, "سبعمئة": 700, "سبعمائة": 700,
    "ثمانمئة": 800, "ثمانمائة": 800, "تسعمئة": 900, "تسعمائة": 900,
    "ألف": 1000, "الف": 1000, "ألفين": 2000, "الفين": 2000, "آلاف": 1000, "الاف": 1000,
    "مليون": 1_000_000, "مليونين": 2_000_000, "ملايين": 1_000_000,
}
_ARABIC_DIGIT_TRANSLATION = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
_RESERVED_TERMS = frozenset({"محجوز", "محجوزة", "محجوزًا", "محجوزا", "reserved"})
_NUMBER_UNIT_TOKENS = frozenset({
    "مرة", "مرات", "عملية", "عمليات", "يوم", "أيام", "ايام", "ساعة", "ساعات",
    "دقيقة", "دقائق", "نسبة", "بالمئة", "بالمائة", "%",
})
_WARNING_TERMS = frozenset({
    "رفض", "مرفوض", "مرفوضة", "تنرفض", "رفضها", "تحذير", "تنبيه", "خطأ",
    "rejected", "declined", "warning", "error",
})
_NEGATION_MODIFIERS = frozenset({"غير", "بدون", "دون"})
_SEMANTIC_COMPANIONS = frozenset({
    "عدد", "موقع", "الشراء", "شراء", "الحقيقي", "حقيقي", "المسموح", "مسموح", "الأساسي", "أساسي",
    "الاساسي", "اساسي", "اليومي", "يومي", "باليوم", "تشتغل", "عام", "عامة",
})
_GENERIC_ENTITY_TERMS = frozenset({
    "البنك", "بنك", "البطاقة", "بطاقة", "العملة", "عملة",
    "bank", "card", "currency",
})
_IMPORTANCE_TERMS = frozenset({
    "الرصيد", "المتاح", "متاح", "فعليًا", "فعليا", "محجوز", "محجوزة", "الحد", "حد",
    "اليومي", "رفض", "مرفوض", "تنرفض", "رفضها", "البنك", "بنك", "البطاقة", "البطاقات",
    "ائتمانية", "الائتمانية", "أونلاين", "اونلاين", "الإلكتروني", "الالكتروني", "إلكتروني",
    "الكتروني", "الدولي", "دولي", "السحب", "سحب", "العمليات", "عمليات", "العملة", "عملة",
    "الخصوصية", "خصوصية", "فعلاً", "فعلًا", "فعلا", "رسوم", "ضريبة", "شحن", "خصم", "مجاني", "تنبيه", "خطأ", "نجاح",
    "balance", "available", "limit", "daily", "reserved", "bank", "card", "online",
    "international", "withdrawal", "currency", "privacy", "rejected", "declined", "fee", "tax",
    "shipping", "discount", "free", "warning", "error", "success",
})


@dataclass(frozen=True, slots=True)
class KeywordToken:
    display_text: str
    source_char_start: int
    source_char_end: int


@dataclass(frozen=True, slots=True)
class KeywordCandidate:
    display_text: str
    semantic_type: str
    source_char_start: int
    source_char_end: int
    score: float
    tokens: tuple[KeywordToken, ...] = ()


class TextSemanticSelector:
    """Select sparse, traceable on-screen keywords from forced-aligned narration.

    The selector is intentionally deterministic. Numeric/amount concepts and a compact
    domain-impact lexicon receive priority; generic speech is suppressed instead of
    becoming subtitle-like text. Every display phrase retains an exact source span so
    TextTiming can map it back to real Forced Alignment timestamps.
    """

    def __init__(
        self,
        *,
        max_keywords_per_beat: int = 2,
        max_display_chars: int = 24,
        min_candidate_score: float = 0.74,
    ) -> None:
        self.max_keywords_per_beat = max(1, max_keywords_per_beat)
        self.max_display_chars = max(8, max_display_chars)
        self.min_candidate_score = min_candidate_score

    def select(self, beat: StoryBeat, transcript: Transcript) -> list[KeywordCandidate]:
        words = self._aligned_words_for_beat(beat, transcript)
        if not words:
            return []

        candidates = self._number_candidates(words)
        candidates.extend(self._semantic_candidates(words, beat))

        deduped: dict[str, KeywordCandidate] = {}
        for candidate in candidates:
            if candidate.score < self.min_candidate_score:
                continue
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
            normalized = cleaned.lower()
            if not cleaned or not self._is_number_token(normalized):
                continue
            if index > 0 and self._is_number_token(self._clean(words[index - 1].text).lower()):
                continue

            number_words = [cleaned]
            last = word
            cursor = index + 1

            # Keep compound written numbers together (e.g. "خمسة آلاف") before
            # attaching currency/unit semantics.
            while cursor < len(words):
                component = self._clean(words[cursor].text)
                if not self._is_number_token(component.lower()):
                    break
                number_words.append(component)
                last = words[cursor]
                cursor += 1

            normalized_number = self._normalize_number_phrase(number_words)
            number_display = normalized_number or " ".join(number_words)
            if word.char_start is None or last.char_end is None:
                continue
            display_parts = [number_display]
            token_parts = [KeywordToken(
                display_text=number_display,
                source_char_start=word.char_start,
                source_char_end=last.char_end,
            )]

            if cursor < len(words):
                unit_word = words[cursor]
                unit = self._clean(unit_word.text)
                unit_normalized = unit.lower()
                if unit_normalized in _CURRENCY_TOKENS or unit_normalized in _NUMBER_UNIT_TOKENS:
                    if unit_word.char_start is not None and unit_word.char_end is not None:
                        display_parts.append(unit)
                        token_parts.append(KeywordToken(
                            display_text=unit,
                            source_char_start=unit_word.char_start,
                            source_char_end=unit_word.char_end,
                        ))
                        last = unit_word
                        cursor += 1

            # Reserved-funds wording often contains a filler token (e.g. "منها") between
            # amount and state. Keep display text concise while timing the visible state
            # to the exact source word that carried it.
            reserved = None
            for lookahead in range(cursor, min(len(words), cursor + 3)):
                reserved_text = self._clean(words[lookahead].text)
                if reserved_text.lower() in _RESERVED_TERMS:
                    reserved = words[lookahead]
                    if reserved.char_start is not None and reserved.char_end is not None:
                        display_parts.append(reserved_text)
                        token_parts.append(KeywordToken(
                            display_text=reserved_text,
                            source_char_start=reserved.char_start,
                            source_char_end=reserved.char_end,
                        ))
                        last = reserved
                    break

            if word.char_start is None or last.char_end is None:
                continue
            display = " ".join(display_parts)
            if len(display) > self.max_display_chars:
                continue
            semantic_type = "warning_amount" if reserved is not None else "amount"
            output.append(KeywordCandidate(
                display_text=display,
                semantic_type=semantic_type,
                source_char_start=word.char_start,
                source_char_end=last.char_end,
                score=1.22 if reserved is not None else 1.10,
                tokens=tuple(token_parts),
            ))
        return output

    def _semantic_candidates(
        self,
        words: list[TranscriptWord],
        beat: StoryBeat,
    ) -> list[KeywordCandidate]:
        output: list[KeywordCandidate] = []
        action_bonus = 0.08 if beat.action in {"EMPHASIZE", "RESULT", "HANDOFF"} else 0.0
        for index, word in enumerate(words):
            cleaned = self._clean(word.text)
            if not self._is_content_word(cleaned):
                continue
            normalized = cleaned.lower()
            if normalized not in _IMPORTANCE_TERMS:
                continue

            base_score = 0.63 if normalized in _GENERIC_ENTITY_TERMS else 0.80
            score = base_score + action_bonus
            phrase = [word]
            # Prefer one compact companion word to make labels natural ("الحد اليومي",
            # "الرصيد المتاح", "الشراء الإلكتروني") without recreating subtitles.
            neighbor = self._best_neighbor(words, index)
            if neighbor is not None:
                combined = f"{cleaned} {self._clean(neighbor.text)}".strip()
                if len(combined) <= self.max_display_chars:
                    phrase.append(neighbor)
                    score += 0.06

                    # Negation is not useful on screen by itself ("الحد غير"). Include
                    # the immediately following content word to complete the concept.
                    neighbor_index = words.index(neighbor)
                    if self._clean(neighbor.text).lower() in _NEGATION_MODIFIERS:
                        follow_index = neighbor_index + 1
                        if follow_index < len(words):
                            follow = words[follow_index]
                            if self._is_content_word(self._clean(follow.text)):
                                candidate_text = " ".join(
                                    self._clean(row.text)
                                    for row in sorted(
                                        [*phrase, follow],
                                        key=lambda row: row.char_start if row.char_start is not None else -1,
                                    )
                                )
                                if len(candidate_text) <= self.max_display_chars:
                                    phrase.append(follow)
                                    score += 0.04

            semantic_type = "warning" if normalized in _WARNING_TERMS else "emphasis"
            candidate = self._candidate_from_words(phrase, semantic_type, score)
            if candidate:
                output.append(candidate)
        return output

    def _best_neighbor(self, words: list[TranscriptWord], index: int) -> TranscriptWord | None:
        options: list[TranscriptWord] = []
        for neighbor_index in (index - 1, index + 1):
            if not 0 <= neighbor_index < len(words):
                continue
            neighbor = words[neighbor_index]
            cleaned = self._clean(neighbor.text)
            normalized = cleaned.lower()
            if not self._is_content_word(cleaned):
                continue
            if (
                normalized in _IMPORTANCE_TERMS
                or normalized in _SEMANTIC_COMPANIONS
                or normalized in _NEGATION_MODIFIERS
            ):
                options.append(neighbor)
        if not options:
            return None
        # Prefer a neighboring importance term, then a following semantic modifier.
        important = [row for row in options if self._clean(row.text).lower() in _IMPORTANCE_TERMS]
        if important:
            return important[0]
        following = [row for row in options if (row.char_start or -1) > (words[index].char_start or -1)]
        return following[0] if following else options[0]

    def _candidate_from_words(
        self,
        words: list[TranscriptWord],
        semantic_type: str,
        score: float,
    ) -> KeywordCandidate | None:
        if not words:
            return None
        ordered = sorted(words, key=lambda row: row.char_start if row.char_start is not None else -1)
        first = ordered[0]
        last = ordered[-1]
        if first.char_start is None or last.char_end is None:
            return None
        display = " ".join(self._clean(word.text) for word in ordered).strip()
        if not display or len(display) > self.max_display_chars:
            return None
        tokens = tuple(
            KeywordToken(
                display_text=self._clean(word.text),
                source_char_start=int(word.char_start),
                source_char_end=int(word.char_end),
            )
            for word in ordered
            if word.char_start is not None and word.char_end is not None and self._clean(word.text)
        )
        return KeywordCandidate(
            display_text=display,
            semantic_type=semantic_type,
            source_char_start=first.char_start,
            source_char_end=last.char_end,
            score=score,
            tokens=tokens,
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
        return min(self.max_keywords_per_beat, 2 if duration >= 3.2 else 1)

    @classmethod
    def _is_number_token(cls, value: str) -> bool:
        return bool(_DIGIT_RE.search(value)) or cls._number_word_value(value) is not None

    @staticmethod
    def _number_word_value(value: str) -> int | None:
        normalized = value.lower()
        if normalized in _ARABIC_NUMBER_VALUES:
            return _ARABIC_NUMBER_VALUES[normalized]
        if normalized.startswith("و") and normalized[1:] in _ARABIC_NUMBER_VALUES:
            return _ARABIC_NUMBER_VALUES[normalized[1:]]
        return None

    @classmethod
    def _normalize_number_phrase(cls, tokens: list[str]) -> str | None:
        if not tokens:
            return None
        if all(_DIGIT_RE.search(token) for token in tokens):
            return "".join(token.translate(_ARABIC_DIGIT_TRANSLATION) for token in tokens)

        values: list[int] = []
        for token in tokens:
            value = cls._number_word_value(token)
            if value is None:
                return None
            values.append(value)

        total = 0
        current = 0
        for value in values:
            if value in {1000, 1_000_000}:
                total += (current or 1) * value
                current = 0
            else:
                current += value
        return str(total + current)

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
        token = _TOKEN_EDGE_RE.sub("", value.strip())
        # Normalize common Arabic conjunction/preposition clitics for display only;
        # source character spans remain unchanged for forced-alignment timing.
        if token.startswith("وال") and len(token) > 4:
            token = token[1:]
        elif token.startswith("فال") and len(token) > 4:
            token = token[1:]
        elif token.startswith("لل") and len(token) > 3:
            token = "ال" + token[2:]
        elif token.startswith("و") and len(token) > 4 and token[1:] in _ARABIC_STOPWORDS:
            token = token[1:]
        return token

    @classmethod
    def _normalize(cls, value: str) -> str:
        return " ".join(cls._clean(value).lower().split())

    @staticmethod
    def _overlaps(left: KeywordCandidate, right: KeywordCandidate) -> bool:
        return (
            left.source_char_start < right.source_char_end
            and left.source_char_end > right.source_char_start
        )
