from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, Iterable

from app.models import (
    AssetActivation,
    PackageModel,
    SceneSource,
    StoryBeat,
    StoryEntity,
    StoryTrigger,
    Transcript,
    TranscriptWord,
    VisualAsset,
)

from .binding import SemanticAssetBinder


_ARABIC_DIACRITICS = re.compile(r"[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED]")
_NON_WORD = re.compile(r"[^0-9A-Za-z\u0600-\u06FF]+", re.UNICODE)
_DIGIT_TRANSLATION = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")


@dataclass(frozen=True, slots=True)
class _PhraseCandidate:
    text: str
    char_start: int | None
    char_end: int | None
    spoken_start: float
    spoken_end: float
    token_count: int


@dataclass(frozen=True, slots=True)
class _VisualSemanticMatch:
    asset_id: str
    phrase_index: int
    confidence: float


class HybridSemanticTextScorer:
    """Fuse deterministic lexical evidence with an optional multilingual encoder.

    The ML backend is optional and lazy. Production can point
    HEXA_SEMANTIC_TEXT_MODEL at a multilingual encoder such as E5. If the model is
    absent or cannot load, Story degrades to conservative deterministic matching
    instead of failing generation.
    """

    def __init__(self, model_name: str | None = None) -> None:
        self.model_name = model_name
        self._tokenizer = None
        self._model = None
        self._torch = None
        self._device = "cpu"
        self._disabled = False
        self._cache: dict[str, object] = {}

    def score(self, query: str, candidates: list[str]) -> tuple[list[float], bool]:
        lexical = [self._lexical_score(query, candidate) for candidate in candidates]
        semantic = self._embedding_scores(query, candidates)
        if semantic is None:
            return lexical, False
        return [
            max(0.0, min(1.0, 0.86 * semantic_score + 0.14 * lexical_score))
            for semantic_score, lexical_score in zip(semantic, lexical)
        ], True

    def _embedding_scores(self, query: str, candidates: list[str]) -> list[float] | None:
        if not self.model_name or self._disabled or not candidates:
            return None
        try:
            self._load()
            query_vector = self._encode([self._prefix(query, query=True)])[0]
            candidate_vectors = self._encode(
                [self._prefix(value, query=False) for value in candidates]
            )
            scores = self._torch.matmul(candidate_vectors, query_vector)
            return [max(0.0, min(1.0, float(value))) for value in scores.tolist()]
        except Exception:
            # Optional semantic inference must never make generation unusable.
            self._disabled = True
            self._tokenizer = None
            self._model = None
            self._torch = None
            self._cache.clear()
            return None

    def _load(self) -> None:
        if self._model is not None:
            return
        import torch
        from transformers import AutoModel, AutoTokenizer

        self._torch = torch
        self._tokenizer = AutoTokenizer.from_pretrained(self.model_name)
        self._model = AutoModel.from_pretrained(self.model_name)
        if torch.cuda.is_available():
            self._device = "cuda"
            self._model = self._model.to(self._device)
        self._model.eval()

    def _encode(self, texts: list[str]):
        uncached = [value for value in texts if value not in self._cache]
        if uncached:
            encoded = self._tokenizer(
                uncached,
                padding=True,
                truncation=True,
                max_length=128,
                return_tensors="pt",
            )
            encoded = {key: value.to(self._device) for key, value in encoded.items()}
            with self._torch.no_grad():
                output = self._model(**encoded)
            hidden = output.last_hidden_state
            mask = encoded["attention_mask"].unsqueeze(-1).expand(hidden.size()).float()
            pooled = (hidden * mask).sum(dim=1) / mask.sum(dim=1).clamp(min=1e-9)
            pooled = self._torch.nn.functional.normalize(pooled, p=2, dim=1).cpu()
            for text, vector in zip(uncached, pooled):
                self._cache[text] = vector
        return self._torch.stack([self._cache[value] for value in texts])

    def _prefix(self, text: str, *, query: bool) -> str:
        if "e5" in (self.model_name or "").casefold():
            return ("query: " if query else "passage: ") + text
        return text

    @classmethod
    def _lexical_score(cls, query: str, candidate: str) -> float:
        left = cls._normalize(query)
        right = cls._normalize(candidate)
        if not left or not right:
            return 0.0
        left_tokens = set(left.split())
        right_tokens = set(right.split())
        overlap = len(left_tokens & right_tokens) / max(1, len(left_tokens | right_tokens))
        containment = 1.0 if left in right or right in left else 0.0
        sequence = SequenceMatcher(None, left, right).ratio()
        left_numbers = {token for token in left_tokens if token.isdigit()}
        right_numbers = {token for token in right_tokens if token.isdigit()}
        number_match = 1.0 if left_numbers and left_numbers & right_numbers else 0.0
        return min(
            1.0,
            overlap * 0.55 + containment * 0.20 + sequence * 0.25 + number_match * 0.35,
        )

    @staticmethod
    def _normalize(value: str) -> str:
        value = unicodedata.normalize("NFKC", value or "")
        value = value.translate(_DIGIT_TRANSLATION)
        value = _ARABIC_DIACRITICS.sub("", value)
        value = value.replace("ـ", "")
        value = _NON_WORD.sub(" ", value.casefold())
        return " ".join(value.split())


class SemanticActivationPlanner:
    """Choose narration anchors for important cutouts without changing visual geometry."""

    _MAX_NGRAM = 4
    _MIN_SEMANTIC_SCORE = 0.68
    _MIN_SEMANTIC_MARGIN = 0.015
    _MIN_LEXICAL_SCORE = 0.72
    _MIN_LEXICAL_MARGIN = 0.08

    def __init__(
        self,
        *,
        semantic_model_name: str | None = None,
        scorer: HybridSemanticTextScorer | None = None,
        visual_backend: Any | None = None,
    ) -> None:
        self.binder = SemanticAssetBinder()
        self.scorer = scorer or HybridSemanticTextScorer(semantic_model_name)
        self.visual_backend = visual_backend
        self._visual_cache: dict[str, dict[str, _VisualSemanticMatch]] = {}

    def enrich(
        self,
        package: PackageModel,
        transcript: Transcript,
        assets: list[VisualAsset],
        beats: list[StoryBeat],
    ) -> list[StoryBeat]:
        scene_by_id = {scene.id: scene for scene in package.scenes}
        assets_by_scene: dict[str, list[VisualAsset]] = {}
        for asset in assets:
            assets_by_scene.setdefault(asset.scene_id, []).append(asset)

        output: list[StoryBeat] = []
        for beat in beats:
            scene = scene_by_id.get(beat.scene_id)
            scene_assets = assets_by_scene.get(beat.scene_id, [])
            if scene is None or not scene_assets or beat.semantic_context is None:
                output.append(beat)
                continue
            activations = self._activations_for_beat(
                package=package,
                transcript=transcript,
                scene=scene,
                assets=scene_assets,
                beat=beat,
            )
            output.append(beat.model_copy(update={"asset_activations": activations}))
        return output

    def _activations_for_beat(
        self,
        *,
        package: PackageModel,
        transcript: Transcript,
        scene: SceneSource,
        assets: list[VisualAsset],
        beat: StoryBeat,
    ) -> list[AssetActivation]:
        binding = self.binder.bind(
            scene=scene,
            assets=assets,
            action=beat.action,
            beat=beat,
        )
        semantic_map = dict(binding.semantic_asset_map)
        entities = self._ordered_entities(beat)
        words = self._beat_words(transcript, scene, beat)
        candidates = self._phrase_candidates(words, package.script)
        asset_by_id = {asset.id: asset for asset in assets}
        activations: list[AssetActivation] = []
        previous_anchor = beat.start
        visual_matches: dict[str, _VisualSemanticMatch] | None = None

        for entity in entities:
            asset_id = semantic_map.get(entity.unit_id)
            asset = asset_by_id.get(asset_id or "")
            if asset is None:
                continue

            explicit = self._explicit_activation(
                entity=entity,
                asset=asset,
                words=words,
                script=package.script,
                scene=scene,
                beat=beat,
            )
            if explicit is not None:
                activations.append(explicit)
                if explicit.spoken_start is not None:
                    previous_anchor = max(previous_anchor, explicit.spoken_start)
                continue

            activation = self._semantic_activation(
                entity=entity,
                asset=asset,
                query=self._semantic_query(entity, asset),
                candidates=candidates,
                beat=beat,
                previous_anchor=previous_anchor,
            )

            # Multimodal inference is deliberately a fallback. It is much more
            # expensive than the multilingual text matcher, so a dense scene must not
            # trigger one VLM request per asset. The first unresolved entity causes one
            # joint scene request; every later unresolved entity reuses that result.
            if activation is None and self.visual_backend is not None:
                if visual_matches is None:
                    visual_matches = self._visual_matches(
                        scene=scene,
                        assets=assets,
                        entities=entities,
                        candidates=candidates,
                        beat=beat,
                    )
                visual_match = visual_matches.get(entity.unit_id)
                visual_asset = asset
                if visual_match is not None and visual_match.confidence >= 0.82:
                    visual_asset = asset_by_id.get(visual_match.asset_id) or asset
                activation = self._visual_activation(
                    entity=entity,
                    asset=visual_asset,
                    match=visual_match,
                    candidates=candidates,
                    beat=beat,
                    previous_anchor=previous_anchor,
                )
                if activation is not None:
                    asset = visual_asset

            if activation is not None:
                activations.append(activation)
                if activation.spoken_start is not None:
                    previous_anchor = max(previous_anchor, activation.spoken_start)
            else:
                # A wrong word anchor is worse than the existing narration-aware fallback.
                activations.append(AssetActivation(
                    asset_id=asset.id,
                    semantic_unit_id=entity.unit_id,
                    confidence=0.0,
                    source="semantic_abstention",
                    policy="FALLBACK",
                    evidence=["no_confident_phrase_match"],
                ))

        by_asset = {row.asset_id: row for row in activations}
        for asset in assets:
            if asset.id in by_asset or not asset.parent_asset_id:
                continue
            parent = by_asset.get(asset.parent_asset_id)
            if parent is None or parent.spoken_start is None or parent.policy == "FALLBACK":
                continue
            inherited = AssetActivation(
                asset_id=asset.id,
                semantic_unit_id=parent.semantic_unit_id,
                trigger_text=parent.trigger_text,
                trigger_char_start=parent.trigger_char_start,
                trigger_char_end=parent.trigger_char_end,
                spoken_start=parent.spoken_start,
                spoken_end=parent.spoken_end,
                confidence=min(0.78, parent.confidence),
                source="parent_semantic_anchor",
                policy="GROUP",
                evidence=["inherits_parent_semantic_time"],
            )
            activations.append(inherited)
            by_asset[asset.id] = inherited

        return activations

    def _visual_activation(
        self,
        *,
        entity: StoryEntity,
        asset: VisualAsset,
        match: _VisualSemanticMatch | None,
        candidates: list[_PhraseCandidate],
        beat: StoryBeat,
        previous_anchor: float,
    ) -> AssetActivation | None:
        if (
            match is None
            or match.asset_id != asset.id
            or match.confidence < 0.78
            or match.phrase_index < 0
            or match.phrase_index >= len(candidates)
        ):
            return None
        chosen = candidates[match.phrase_index]
        if (
            chosen.spoken_start < previous_anchor - 0.08
            or chosen.spoken_start < beat.start - 0.02
            or chosen.spoken_start > beat.end - 0.025
        ):
            return None
        return AssetActivation(
            asset_id=asset.id,
            semantic_unit_id=entity.unit_id,
            trigger_text=chosen.text,
            trigger_char_start=chosen.char_start,
            trigger_char_end=chosen.char_end,
            spoken_start=chosen.spoken_start,
            spoken_end=chosen.spoken_end,
            confidence=match.confidence,
            source="vlm_joint_scene_match",
            policy="SEMANTIC",
            evidence=["joint_visual_asset_phrase_match"],
        )

    def _visual_matches(
        self,
        *,
        scene: SceneSource,
        assets: list[VisualAsset],
        entities: list[StoryEntity],
        candidates: list[_PhraseCandidate],
        beat: StoryBeat,
    ) -> dict[str, _VisualSemanticMatch]:
        backend = self.visual_backend
        if (
            backend is None
            or not getattr(backend, "enabled", False)
            or not entities
            or not candidates
            or len(assets) < 2
        ):
            return {}

        cache_key = beat.id
        cached = self._visual_cache.get(cache_key)
        if cached is not None:
            return cached

        phrase_rows = [
            {
                "index": index,
                "text": row.text,
                "spoken_start": round(row.spoken_start, 3),
            }
            for index, row in enumerate(candidates)
            if row.token_count <= 3
        ][:72]
        asset_rows = []
        for asset in assets:
            bbox = list(asset.source_bbox) if asset.source_bbox else None
            asset_rows.append({
                "asset_id": asset.id,
                "role": asset.role,
                "bbox": bbox,
                "independent": asset.can_animate_independently,
                "parent_asset_id": asset.parent_asset_id,
            })
        entity_rows = [{
            "unit_id": entity.unit_id,
            "semantic_name": entity.semantic_name,
            "entity_type": entity.entity_type,
            "role": entity.role,
            "narrative_function": entity.narrative_function,
            "semantic_intent": entity.semantic_intent,
        } for entity in entities]

        prompt = (
            "You are the semantic synchronization matcher for a production video editor. "
            "The image is the authored final scene. Do not redesign it. "
            "Return one JSON object only with key 'matches'. Each match must contain "
            "unit_id, asset_id, phrase_index, confidence. Choose only IDs and phrase "
            "indices supplied below. Match a semantic unit to the visible cutout that "
            "actually represents it, then to the spoken phrase that introduces that "
            "meaning. Preserve narration order. Do not force decorative or ambiguous "
            "objects; omit uncertain matches. confidence must be 0..1. "
            f"Narration: {beat.narration!r}. "
            f"Assets: {json.dumps(asset_rows, ensure_ascii=False)}. "
            f"Semantic units: {json.dumps(entity_rows, ensure_ascii=False)}. "
            f"Phrase candidates: {json.dumps(phrase_rows, ensure_ascii=False)}."
        )
        try:
            payload = backend.decide(scene.image_path, prompt)
        except Exception:
            payload = None
        parsed: dict[str, _VisualSemanticMatch] = {}
        valid_assets = {asset.id for asset in assets}
        valid_entities = {entity.unit_id for entity in entities}
        valid_phrase_indices = {row["index"] for row in phrase_rows}
        if isinstance(payload, dict) and isinstance(payload.get("matches"), list):
            for row in payload["matches"]:
                if not isinstance(row, dict):
                    continue
                unit_id = str(row.get("unit_id") or "")
                asset_id = str(row.get("asset_id") or "")
                try:
                    phrase_index = int(row.get("phrase_index"))
                    confidence = float(row.get("confidence"))
                except (TypeError, ValueError):
                    continue
                if (
                    unit_id not in valid_entities
                    or asset_id not in valid_assets
                    or phrase_index not in valid_phrase_indices
                    or not 0.0 <= confidence <= 1.0
                    or confidence < 0.72
                ):
                    continue
                current = parsed.get(unit_id)
                candidate = _VisualSemanticMatch(
                    asset_id=asset_id,
                    phrase_index=phrase_index,
                    confidence=confidence,
                )
                if current is None or candidate.confidence > current.confidence:
                    parsed[unit_id] = candidate

        self._visual_cache[cache_key] = parsed
        return parsed

    def _semantic_activation(
        self,
        *,
        entity: StoryEntity,
        asset: VisualAsset,
        query: str,
        candidates: list[_PhraseCandidate],
        beat: StoryBeat,
        previous_anchor: float,
    ) -> AssetActivation | None:
        if not query or not candidates:
            return None
        viable = [
            row for row in candidates
            if row.spoken_start >= previous_anchor - 0.08
            and row.spoken_start <= beat.end - 0.025
            and row.spoken_end >= beat.start
        ]
        if not viable:
            return None

        scores, semantic_used = self.scorer.score(query, [row.text for row in viable])
        ranked = sorted(range(len(viable)), key=lambda index: scores[index], reverse=True)
        if not ranked:
            return None
        best_index = ranked[0]
        best = scores[best_index]
        second = scores[ranked[1]] if len(ranked) > 1 else 0.0
        margin = best - second
        accepted = (
            (
                semantic_used
                and (
                    best >= 0.80
                    or (
                        best >= self._MIN_SEMANTIC_SCORE
                        and margin >= self._MIN_SEMANTIC_MARGIN
                    )
                )
            )
            or (
                not semantic_used
                and best >= self._MIN_LEXICAL_SCORE
                and margin >= self._MIN_LEXICAL_MARGIN
            )
        )
        if not accepted:
            return None

        chosen = viable[best_index]
        return AssetActivation(
            asset_id=asset.id,
            semantic_unit_id=entity.unit_id,
            trigger_text=chosen.text,
            trigger_char_start=chosen.char_start,
            trigger_char_end=chosen.char_end,
            spoken_start=chosen.spoken_start,
            spoken_end=chosen.spoken_end,
            confidence=max(0.0, min(1.0, best)),
            source="multilingual_semantic_match" if semantic_used else "lexical_semantic_match",
            policy="SEMANTIC",
            evidence=[
                f"score={best:.3f}",
                f"margin={margin:.3f}",
                f"query={query}",
            ],
        )

    def _explicit_activation(
        self,
        *,
        entity: StoryEntity,
        asset: VisualAsset,
        words: list[TranscriptWord],
        script: str | None,
        scene: SceneSource,
        beat: StoryBeat,
    ) -> AssetActivation | None:
        for kind, trigger in (
            ("focus_trigger", entity.focus_trigger),
            ("appear_trigger", entity.appear_trigger),
        ):
            span_words = self._words_for_trigger(trigger, words, script, scene)
            if not span_words:
                continue

            # Many packages put the whole scene sentence on every unit. That is coarse
            # scene evidence, not a trustworthy word-level trigger.
            coarse_limit = max(5, int(len(words) * 0.70))
            if len(span_words) >= coarse_limit and len(words) > 4:
                continue

            start = span_words[0].start
            if start < beat.start - 0.02 or start > beat.end - 0.025:
                continue
            return AssetActivation(
                asset_id=asset.id,
                semantic_unit_id=entity.unit_id,
                trigger_text=self._text_for_words(span_words, script),
                trigger_char_start=span_words[0].char_start,
                trigger_char_end=span_words[-1].char_end,
                spoken_start=start,
                spoken_end=span_words[-1].end,
                confidence=0.98 if kind == "focus_trigger" else 0.94,
                source=f"final_package_{kind}",
                policy="EXPLICIT",
                evidence=["narrow_declared_trigger", kind],
            )
        return None

    def _beat_words(
        self,
        transcript: Transcript,
        scene: SceneSource,
        beat: StoryBeat,
    ) -> list[TranscriptWord]:
        trigger = beat.semantic_context.event_trigger if beat.semantic_context else None
        char_start = trigger.global_char_start if trigger else None
        char_end = trigger.global_char_end if trigger else None
        if char_start is None:
            char_start = scene.script_char_start
        if char_end is None:
            char_end = scene.script_char_end

        if char_start is not None and char_end is not None:
            rows = [
                word for word in transcript.words
                if word.char_start is not None
                and word.char_end is not None
                and word.char_end > char_start
                and word.char_start <= char_end + 1
            ]
            if rows:
                return rows

        audio_start = beat.audio_start if beat.audio_start is not None else beat.start
        audio_end = beat.audio_end if beat.audio_end is not None else beat.end
        return [
            word for word in transcript.words
            if word.end > audio_start and word.start < audio_end
        ]

    def _phrase_candidates(
        self,
        words: list[TranscriptWord],
        script: str | None,
    ) -> list[_PhraseCandidate]:
        if not words:
            return []
        output: list[_PhraseCandidate] = []
        seen: set[tuple[int | None, int | None, str]] = set()
        for start_index in range(len(words)):
            for length in range(1, min(self._MAX_NGRAM, len(words) - start_index) + 1):
                rows = words[start_index:start_index + length]
                text = self._text_for_words(rows, script)
                key = (rows[0].char_start, rows[-1].char_end, text)
                if not text or key in seen:
                    continue
                seen.add(key)
                output.append(_PhraseCandidate(
                    text=text,
                    char_start=rows[0].char_start,
                    char_end=rows[-1].char_end,
                    spoken_start=rows[0].start,
                    spoken_end=rows[-1].end,
                    token_count=length,
                ))
        output.sort(key=lambda row: (row.spoken_start, row.token_count, row.spoken_end))
        return output

    @staticmethod
    def _semantic_query(entity: StoryEntity, asset: VisualAsset) -> str:
        values = [
            value for value in (
                entity.semantic_name,
                entity.entity_type,
                entity.narrative_function,
                entity.semantic_intent,
                asset.role,
            )
            if value
        ]
        for key in ("label", "description", "visual_label", "meaning", "concept"):
            value = entity.package_metadata.get(key)
            if isinstance(value, str) and value.strip():
                values.append(value.strip())
        return " ; ".join(dict.fromkeys(values))

    @staticmethod
    def _ordered_entities(beat: StoryBeat) -> list[StoryEntity]:
        context = beat.semantic_context
        if context is None:
            return []
        by_id = {entity.unit_id: entity for entity in context.entities}
        ordered: list[StoryEntity] = []
        for unit_id in beat.semantic_targets:
            entity = by_id.get(unit_id)
            if entity is not None and entity not in ordered:
                ordered.append(entity)
        for entity in context.entities:
            if entity not in ordered:
                ordered.append(entity)
        return ordered

    @staticmethod
    def _words_for_trigger(
        trigger: StoryTrigger | None,
        words: list[TranscriptWord],
        script: str | None,
        scene: SceneSource,
    ) -> list[TranscriptWord]:
        if trigger is None:
            return []
        if trigger.global_char_start is not None and trigger.global_char_end is not None:
            return [
                word for word in words
                if word.char_start is not None
                and word.char_end is not None
                and word.char_end > trigger.global_char_start
                and word.char_start <= trigger.global_char_end + 1
            ]

        phrase = (trigger.phrase or "").strip()
        if not phrase or not script:
            return []

        scene_start = scene.script_char_start or 0
        scene_end = (
            scene.script_char_end + 1
            if scene.script_char_end is not None
            else len(script)
        )
        haystack = script[scene_start:scene_end]
        occurrence = max(1, trigger.occurrence_in_scene or 1)
        cursor = 0
        found = -1
        for _ in range(occurrence):
            found = haystack.find(phrase, cursor)
            if found < 0:
                return []
            cursor = found + len(phrase)

        absolute_start = scene_start + found
        absolute_end = absolute_start + len(phrase)
        return [
            word for word in words
            if word.char_start is not None
            and word.char_end is not None
            and word.char_end > absolute_start
            and word.char_start < absolute_end
        ]

    @staticmethod
    def _text_for_words(words: Iterable[TranscriptWord], script: str | None) -> str:
        rows = list(words)
        if not rows:
            return ""
        char_start = rows[0].char_start
        char_end = rows[-1].char_end
        if (
            script is not None
            and char_start is not None
            and char_end is not None
            and 0 <= char_start < char_end <= len(script)
        ):
            return script[char_start:char_end].strip()
        return " ".join(word.text for word in rows).strip()
