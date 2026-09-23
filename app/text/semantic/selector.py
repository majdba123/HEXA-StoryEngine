from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from difflib import SequenceMatcher

from app.models import PackageModel, SceneSource, StoryBeat, Transcript, TranscriptWord

_TOKEN_EDGE_RE = re.compile(r"^[\W_]+|[\W_]+$", re.UNICODE)
_DIGIT_RE = re.compile(r"[0-9٠-٩]")

_ARABIC_STOPWORDS = frozenset({
    "في", "من", "على", "إلى", "الى", "عن", "مع", "هذا", "هذه", "ذلك", "تلك",
    "هو", "هي", "هم", "كما", "لكن", "او", "أو", "ثم", "قد", "كان", "كانت",
    "يكون", "تكون", "إذا", "اذا", "كل", "أي", "اي", "ما", "لا", "لم", "لن",
    "و", "ف", "ب", "ل", "التي", "الذي", "عند", "عندما", "بعد", "قبل", "فقط",
    "إن", "ان", "إنك", "انك", "لك", "منها", "له", "لها", "اللي", "هنا", "كذا",
    "خلال", "بعدها", "وحتى", "حتى", "عشان", "عنها", "منه", "منهم", "منهن",
    "فيه", "فيها", "فيهم", "داخل", "خارج", "بدون", "دون", "أحد", "احد",
    "شيء", "شي", "تقريبًا", "تقريبا", "غالبًا", "غالبا", "عنه", "عنها",
    "عليه", "عليها", "إليه", "اليه", "إليها", "اليها", "أمام", "امام", "قدام",
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
_WEAK_STANDALONE_TERMS = frozenset({
    "يحاول", "تحاول", "نحاول", "يقلل", "تقلل", "يقدر", "تقدر", "يمكن", "يبدأ", "تبدأ",
    "يستخدم", "تستخدم", "يكون", "تكون", "يصير", "يعمل", "تعمل", "يسوي",
    "يخلي", "يخليه", "يريد", "تريد",
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
        max_keywords_per_beat: int = 3,
        max_display_chars: int = 24,
        min_candidate_score: float = 0.74,
    ) -> None:
        self.max_keywords_per_beat = max(1, max_keywords_per_beat)
        self.max_display_chars = max(8, max_display_chars)
        self.min_candidate_score = min_candidate_score

    def select(
        self,
        beat: StoryBeat,
        transcript: Transcript,
        *,
        package: PackageModel | None = None,
    ) -> list[KeywordCandidate]:
        words = self._aligned_words_for_beat(beat, transcript)
        if not words:
            return []

        candidates = self._number_candidates(words)
        package_candidates = self._package_semantic_candidates(words, beat, package)
        if package_candidates:
            # A semantic Final Package is authoritative for topic wording. Do not fill
            # unused text budget with unrelated generic speech merely to increase count.
            candidates.extend(package_candidates)
        else:
            # Topic-agnostic fallback for legacy packages that carry no usable semantic
            # bindings. This path does not depend on a specific business domain.
            candidates.extend(self._generic_semantic_candidates(words, beat, package))
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

    def _package_semantic_candidates(
        self,
        words: list[TranscriptWord],
        beat: StoryBeat,
        package: PackageModel | None,
    ) -> list[KeywordCandidate]:
        """Derive on-screen keywords from the Final Package semantic contract.

        The Final Package decides what concepts matter; Text only chooses a compact
        exact-script phrase suitable for display. Rendered wording is never invented,
        so TextTiming can continue to use canonical-script character spans as the
        authority for forced-alignment timestamps.
        """
        if package is None or not package.script or not package.semantic_bindings:
            return []
        scenes = package.semantic_bindings.get("scenes")
        if not isinstance(scenes, list):
            return []
        binding_scene = next(
            (
                row for row in scenes
                if isinstance(row, dict) and row.get("scene_id") == beat.scene_id
            ),
            None,
        )
        if binding_scene is None:
            return []
        scene = next((row for row in package.scenes if row.id == beat.scene_id), None)
        groups = binding_scene.get("semantic_groups")
        assets = [row for row in binding_scene.get("assets", []) if isinstance(row, dict)]
        assets_by_id = {
            str(row.get("asset_id")): row
            for row in assets
            if row.get("asset_id")
        }

        phrase_rows: list[tuple[str, list[dict]]] = []
        if isinstance(groups, list) and groups:
            for group in groups:
                if not isinstance(group, dict):
                    continue
                phrase = str(group.get("script_text") or "").strip()
                if not phrase:
                    continue
                group_assets = [
                    assets_by_id[asset_id]
                    for asset_id in group.get("asset_ids", [])
                    if asset_id in assets_by_id
                ]
                phrase_rows.append((phrase, group_assets))
        else:
            grouped: dict[str, list[dict]] = {}
            for asset in assets:
                phrase = str(asset.get("script_text") or "").strip()
                if phrase:
                    grouped.setdefault(phrase, []).append(asset)
            phrase_rows.extend(grouped.items())

        if not phrase_rows:
            return []

        corpus_frequency = self._content_frequency(package.script)
        output: list[KeywordCandidate] = []
        for phrase, semantic_assets in phrase_rows:
            span = self._phrase_span(package.script, scene, phrase, words)
            if span is None:
                continue
            phrase_words = [
                word for word in words
                if word.char_start is not None
                and word.char_end is not None
                and word.char_end > span[0]
                and word.char_start < span[1]
            ]
            if not phrase_words:
                continue

            produced = False
            for semantic_asset in semantic_assets:
                binding_type = str(semantic_asset.get("binding_type") or "").upper()
                if binding_type in {"SUPPORT", "PARENT", "AMBIGUOUS"}:
                    continue
                semantic_terms, explicit_terms = self._semantic_evidence_terms([semantic_asset])
                rows = self._semantic_phrase_windows(
                    phrase_words,
                    semantic_assets=[semantic_asset],
                    semantic_terms=semantic_terms,
                    explicit_terms=explicit_terms,
                    corpus_frequency=corpus_frequency,
                    action=beat.action,
                    require_semantic_match=True,
                    require_full_semantic_coverage=False,
                )
                if rows:
                    produced = True
                    output.extend(rows)

            aggregate_terms, aggregate_explicit = self._semantic_evidence_terms(semantic_assets)
            output.extend(self._semantic_phrase_windows(
                phrase_words,
                semantic_assets=semantic_assets,
                semantic_terms=aggregate_terms,
                explicit_terms=aggregate_explicit,
                corpus_frequency=corpus_frequency,
                action=beat.action,
                require_semantic_match=True,
                require_full_semantic_coverage=True,
            ))
            if not produced:
                output.extend(self._semantic_phrase_windows(
                    phrase_words,
                    semantic_assets=semantic_assets,
                    semantic_terms=aggregate_terms,
                    explicit_terms=aggregate_explicit,
                    corpus_frequency=corpus_frequency,
                    action=beat.action,
                    require_semantic_match=False,
                    require_full_semantic_coverage=False,
                ))
        return output

    def _generic_semantic_candidates(
        self,
        words: list[TranscriptWord],
        beat: StoryBeat,
        package: PackageModel | None,
    ) -> list[KeywordCandidate]:
        """Topic-agnostic fallback based on linguistic salience, not domain words."""
        corpus = package.script if package is not None and package.script else beat.narration
        frequency = self._content_frequency(corpus or "")
        output: list[KeywordCandidate] = []
        action_bonus = 0.05 if beat.action in {"EMPHASIZE", "RESULT", "HANDOFF"} else 0.0
        for index, word in enumerate(words):
            cleaned = self._clean(word.text)
            if not self._is_content_word(cleaned):
                continue
            norm = self._semantic_lexeme(cleaned)
            if not norm:
                continue
            rarity = 1.0 / max(1, frequency.get(norm, 1))
            score = 0.70 + min(0.10, rarity * 0.06) + action_bonus
            if len(cleaned) >= 5:
                score += 0.03
            candidate = self._candidate_from_words([word], "keyword", score)
            if candidate:
                output.append(candidate)

            if index + 1 < len(words):
                neighbor = words[index + 1]
                neighbor_clean = self._clean(neighbor.text)
                if self._is_content_word(neighbor_clean):
                    combined = f"{cleaned} {neighbor_clean}".strip()
                    if len(combined) <= self.max_display_chars:
                        pair = self._candidate_from_words(
                            [word, neighbor], "keyword", score + 0.045,
                        )
                        if pair:
                            output.append(pair)
        return output

    def _semantic_phrase_windows(
        self,
        words: list[TranscriptWord],
        *,
        semantic_assets: list[dict],
        semantic_terms: set[str],
        explicit_terms: set[str],
        corpus_frequency: Counter[str],
        action: str,
        require_semantic_match: bool,
        require_full_semantic_coverage: bool,
    ) -> list[KeywordCandidate]:
        output: list[KeywordCandidate] = []
        binding_types = {
            str(row.get("binding_type") or "").upper() for row in semantic_assets
        }
        binding_bonus = (
            0.12 if "EXPLICIT" in binding_types
            else 0.055 if "SEMANTIC" in binding_types
            else 0.0
        )
        roles = {
            str(row.get("semantic_role") or row.get("role") or "").upper()
            for row in semantic_assets
        }
        role_bonus = 0.035 if roles & {"PRIMARY", "RESULT", "ACTION", "OBJECT"} else 0.0
        action_bonus = 0.035 if action in {"EMPHASIZE", "RESULT", "HANDOFF"} else 0.0

        max_window = min(3, len(words))
        for size in range(1, max_window + 1):
            for start in range(0, len(words) - size + 1):
                window = words[start:start + size]
                if self._crosses_clause_boundary(window):
                    continue
                cleaned = [self._clean(row.text) for row in window]
                if not cleaned or any(not token for token in cleaned):
                    continue
                if not self._is_content_word(cleaned[0]) or not self._is_content_word(cleaned[-1]):
                    continue
                display = " ".join(cleaned)
                if len(display) > self.max_display_chars:
                    continue
                content = [token for token in cleaned if self._is_content_word(token)]
                if not content:
                    continue
                if size == 1 and cleaned[0].lower() in _WEAK_STANDALONE_TERMS:
                    continue
                strong_content = [
                    token for token in content
                    if token.lower() not in _WEAK_STANDALONE_TERMS
                ]
                if not strong_content:
                    continue

                lexemes = [self._semantic_lexeme(token) for token in content]
                semantic_matches = sum(
                    1 for token in lexemes
                    if token and any(self._terms_related(token, term) for term in semantic_terms)
                )
                explicit_matches = sum(
                    1 for token in lexemes
                    if token and any(self._terms_related(token, term) for term in explicit_terms)
                )
                if require_semantic_match and semantic_matches + explicit_matches == 0:
                    continue
                if require_full_semantic_coverage and semantic_matches < len(content):
                    continue

                rarity = sum(
                    1.0 / max(1, corpus_frequency.get(token, 1))
                    for token in lexemes if token
                ) / max(1, len(lexemes))
                score = 0.74 + binding_bonus + role_bonus + action_bonus
                score += min(0.28, semantic_matches * 0.14)
                score += min(0.18, explicit_matches * 0.09)
                score += min(0.07, rarity * 0.05)
                unmatched_content = max(0, len(content) - semantic_matches)
                score -= 0.045 * unmatched_content
                score -= 0.025 * (size - 1)
                semantic_type = (
                    "emphasis"
                    if "EXPLICIT" in binding_types or semantic_matches or explicit_matches
                    else "keyword"
                )
                candidate = self._candidate_from_words(window, semantic_type, score)
                if candidate:
                    output.append(candidate)
        return output

    @staticmethod
    def _crosses_clause_boundary(words: list[TranscriptWord]) -> bool:
        if len(words) <= 1:
            return False
        boundary = ("،", "؛", ",", ";", ".", "!", "?", "؟", ":")
        return any(str(word.text).rstrip().endswith(boundary) for word in words[:-1])

    @classmethod
    def _semantic_evidence_terms(cls, assets: list[dict]) -> tuple[set[str], set[str]]:
        all_terms: set[str] = set()
        explicit_terms: set[str] = set()
        fields = ("semantic_meaning", "visual_concept", "semantic_role")
        for asset in assets:
            row_terms: set[str] = set()
            for field in fields:
                value = str(asset.get(field) or "")
                for raw in re.findall(r"[w؀-ۿ]+", value, flags=re.UNICODE):
                    term = cls._semantic_lexeme(raw)
                    if term:
                        row_terms.add(term)
            all_terms.update(row_terms)
            if str(asset.get("binding_type") or "").upper() == "EXPLICIT":
                explicit_terms.update(row_terms)
        return all_terms, explicit_terms

    @classmethod
    def _content_frequency(cls, text: str) -> Counter[str]:
        output: Counter[str] = Counter()
        for raw in re.findall(r"[w؀-ۿ]+", text, flags=re.UNICODE):
            cleaned = cls._clean(raw)
            if not cls._is_content_word(cleaned):
                continue
            term = cls._semantic_lexeme(cleaned)
            if term:
                output[term] += 1
        return output

    @classmethod
    def _semantic_lexeme(cls, value: str) -> str:
        token = cls._clean(value).lower()
        token = re.sub(r"[ًٌٍَُِّْـ]", "", token)
        token = token.translate(
            str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ى": "ي", "ة": "ه"})
        )
        if token.startswith("وال") and len(token) > 5:
            token = token[1:]
        elif token.startswith("فال") and len(token) > 5:
            token = token[1:]
        if token.startswith("ال") and len(token) > 4:
            token = token[2:]
        return token

    @classmethod
    def _terms_related(cls, left: str, right: str) -> bool:
        if left == right:
            return True
        if min(len(left), len(right)) < 4:
            return False
        if left in right or right in left:
            return True
        left_key = cls._morphology_key(left)
        right_key = cls._morphology_key(right)
        if min(len(left_key), len(right_key)) < 4:
            return False
        if left_key in right_key or right_key in left_key:
            return True
        return SequenceMatcher(None, left_key, right_key).ratio() >= 0.72

    @staticmethod
    def _morphology_key(value: str) -> str:
        token = value
        if len(token) > 5 and token[0] in {"و", "ف"}:
            token = token[1:]
        if len(token) > 5 and token[0] in {"ي", "ت", "ن", "ا"}:
            token = token[1:]
        for suffix in (
            "يات", "ات", "ون", "ين", "ها", "هم", "هن", "نا", "ية", "يه", "ه", "ك",
        ):
            if token.endswith(suffix) and len(token) - len(suffix) >= 4:
                token = token[:-len(suffix)]
                break
        return token

    @staticmethod
    def _phrase_span(
        script: str,
        scene: SceneSource | None,
        phrase: str,
        words: list[TranscriptWord],
    ) -> tuple[int, int] | None:
        if not phrase:
            return None
        candidates: list[int] = []
        cursor = 0
        while True:
            index = script.find(phrase, cursor)
            if index < 0:
                break
            candidates.append(index)
            cursor = index + 1
        if not candidates:
            return None

        if scene is not None and scene.script_char_start is not None and scene.script_char_end is not None:
            scene_start = scene.script_char_start
            scene_end = scene.script_char_end + 1
            in_scene = [
                index for index in candidates
                if index < scene_end and index + len(phrase) > scene_start
            ]
            if in_scene:
                candidates = in_scene

        word_starts = [row.char_start for row in words if row.char_start is not None]
        word_ends = [row.char_end for row in words if row.char_end is not None]
        if word_starts and word_ends:
            beat_start = min(word_starts)
            beat_end = max(word_ends)
            candidates.sort(
                key=lambda index: -max(
                    0,
                    min(index + len(phrase), beat_end) - max(index, beat_start),
                )
            )
        start = candidates[0]
        return start, start + len(phrase)

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
        if duration >= 5.0:
            return min(self.max_keywords_per_beat, 3)
        if duration >= 2.2:
            return min(self.max_keywords_per_beat, 2)
        return 1

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
        elif token.startswith("وا") and len(token) > 6:
            token = token[1:]
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
