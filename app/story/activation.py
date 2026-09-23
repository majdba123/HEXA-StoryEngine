from __future__ import annotations

import json
import logging
import math
import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, Iterable

from app.shared.errors import DependencyUnavailableError
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
from .identity import VisualIdentityBinder
from .windows import ScheduledStoryBeat, schedule_windows


_LOG = logging.getLogger(__name__)

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


class HybridSemanticTextScorer:
    """Fuse deterministic lexical evidence with an optional multilingual encoder.

    The ML backend is optional and lazy. Production can point
    HEXA_SEMANTIC_TEXT_MODEL at a multilingual encoder such as E5. If the model is
    absent or cannot load, Story degrades to conservative deterministic matching
    instead of failing generation.
    """

    def __init__(self, model_name: str | None = None, *, required: bool = False) -> None:
        self.model_name = model_name
        self.required = required
        self._tokenizer = None
        self._model = None
        self._torch = None
        self._device = "cpu"
        self._disabled = False
        self._cache: dict[str, object] = {}
        self.runtime_available: bool | None = None
        self.runtime_error: str | None = None

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
        if not candidates:
            return None
        if not self.ensure_available():
            return None
        try:
            query_vector = self._encode([self._prefix(query, query=True)])[0]
            candidate_vectors = self._encode(
                [self._prefix(value, query=False) for value in candidates]
            )
            scores = self._torch.matmul(candidate_vectors, query_vector)
            values = [float(value) for value in scores.tolist()]
            if not all(math.isfinite(value) for value in values):
                raise ValueError("semantic model produced nonfinite scores")
            return [max(0.0, min(1.0, value)) for value in values]
        except Exception as exc:
            self._runtime_failure(exc)
            return None

    def ensure_available(self) -> bool:
        if self.runtime_available is True:
            return True
        if self._disabled:
            if self.required:
                raise DependencyUnavailableError(
                    "semantic runtime unavailable", details={
                        "model": self.model_name, "error": self.runtime_error,
                        "code": "SEMANTIC_RUNTIME_UNAVAILABLE",
                    },
                )
            return False
        if not self.model_name:
            self._runtime_failure(RuntimeError("semantic_model_not_configured"))
            return False
        try:
            self._load()
            self.runtime_available = True
            self.runtime_error = None
            return True
        except Exception as exc:
            self._runtime_failure(exc)
            return False

    def _runtime_failure(self, exc: Exception) -> None:
        self.runtime_available = False
        self.runtime_error = str(exc)
        self._disabled = True
        self._tokenizer = self._model = self._torch = None
        self._cache.clear()
        _LOG.error("SEMANTIC_RUNTIME_UNAVAILABLE model=%s error=%s", self.model_name, exc)
        if self.required:
            raise DependencyUnavailableError(
                "semantic runtime unavailable", details={
                    "model": self.model_name, "error": self.runtime_error,
                    "code": "SEMANTIC_RUNTIME_UNAVAILABLE",
                },
            ) from exc

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
        uncached = list(dict.fromkeys(value for value in texts if value not in self._cache))
        for offset in range(0, len(uncached), 32):
            batch = uncached[offset:offset + 32]
            encoded = self._tokenizer(
                batch,
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
            for text, vector in zip(batch, pooled):
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

    _MAX_NGRAM = 8
    _MAX_ASSIGNMENT_CANDIDATES = 8
    _MIN_SEMANTIC_SCORE = 0.68
    _MIN_SEMANTIC_MARGIN = 0.015
    _MIN_LEXICAL_SCORE = 0.72
    _MIN_LEXICAL_MARGIN = 0.08

    def __init__(
        self,
        *,
        semantic_model_name: str | None = None,
        semantic_model_required: bool = False,
        scorer: HybridSemanticTextScorer | None = None,
    ) -> None:
        self.binder = SemanticAssetBinder()
        self.identity_binder = VisualIdentityBinder()
        self._identity_incomplete_beats: set[str] = set()
        self.scorer = scorer or HybridSemanticTextScorer(
            semantic_model_name, required=semantic_model_required
        )
        self._eligible_asset_ids: set[str] = set()
        self._trusted_eligible_ids: set[str] = set()
        self._inherited_eligible_ids: set[str] = set()
        self.diagnostics: dict[str, Any] = {}
        self._decisions: dict[tuple[str, str], dict[str, Any]] = {}

    def enrich(
        self,
        package: PackageModel,
        transcript: Transcript,
        assets: list[VisualAsset],
        beats: list[StoryBeat],
    ) -> list[StoryBeat]:
        self._decisions.clear()
        self._eligible_asset_ids.clear()
        self._trusted_eligible_ids.clear()
        self._inherited_eligible_ids.clear()
        self._identity_incomplete_beats.clear()
        self.diagnostics = {
            "semantic_runtime_available": None, "trusted_count": 0,
            "inherited_count": 0, "abstained_count": 0, "runtime_failure_count": 0,
            "semantic_authority": "final_package",
            "eligible_asset_count": 0, "trusted_eligible_count": 0,
            "inherited_eligible_count": 0, "eligible_coverage": 0.0,
            "assets": [],
            "visual_identity": [],
        }
        if isinstance(self.scorer, HybridSemanticTextScorer):
            if not package.semantic_bindings:
                try:
                    self.scorer.ensure_available()
                finally:
                    self._runtime_diagnostics()
            else:
                self._runtime_diagnostics()
        scene_by_id = {scene.id: scene for scene in package.scenes}
        assets_by_scene: dict[str, list[VisualAsset]] = {}
        for asset in assets:
            assets_by_scene.setdefault(asset.scene_id, []).append(asset)

        output: list[StoryBeat] = []
        for beat in beats:
            scene = scene_by_id.get(beat.scene_id)
            scene_assets = assets_by_scene.get(beat.scene_id, [])
            if scene is None or not scene_assets:
                output.append(beat)
                continue
            activations = self._activations_for_beat(
                package=package,
                transcript=transcript,
                scene=scene,
                assets=scene_assets,
                beat=beat,
            )
            windows = schedule_windows(
                activations, beat, transcript.duration, set(beat.primary_asset_ids),
            )
            data = beat.model_dump()
            data["asset_activations"] = windows
            output.append(ScheduledStoryBeat.model_validate(data))
            for row in windows:
                key = {"OWN_WINDOW": "trusted_count", "INHERITED_WINDOW": "inherited_count",
                       "SAFE_ABSTENTION": "abstained_count"}[row.activation_policy]
                self.diagnostics[key] += 1
                if row.asset_id in self._eligible_asset_ids:
                    if row.activation_policy == "OWN_WINDOW":
                        self._trusted_eligible_ids.add(row.asset_id)
                    elif row.activation_policy == "INHERITED_WINDOW":
                        self._inherited_eligible_ids.add(row.asset_id)
                self._record_diagnostic(beat, row)
        eligible = len(self._eligible_asset_ids)
        trusted = len(self._trusted_eligible_ids)
        inherited = len(self._inherited_eligible_ids)
        self.diagnostics.update(
            eligible_asset_count=eligible,
            trusted_eligible_count=trusted,
            inherited_eligible_count=inherited,
            eligible_coverage=((trusted + inherited) / eligible if eligible else 1.0),
        )
        self._runtime_diagnostics()
        _LOG.info("Story semantic summary: %s", json.dumps(
            {
                k: v
                for k, v in self.diagnostics.items()
                if k not in {"assets", "visual_identity"}
            },
            ensure_ascii=False,
        ))
        return output

    def _runtime_diagnostics(self) -> None:
        if isinstance(self.scorer, HybridSemanticTextScorer):
            self.diagnostics.update(
                semantic_runtime_available=self.scorer.runtime_available,
                semantic_runtime_error=self.scorer.runtime_error,
                runtime_failure_count=int(self.scorer.runtime_available is False),
            )

    def _record_diagnostic(self, beat: StoryBeat, row: AssetActivation) -> None:
        decision = dict(self._decisions.get((beat.id, row.asset_id), {}))
        entities = self._ordered_entities(beat)
        entity = next((e for e in entities if e.unit_id == row.semantic_unit_id), None)
        source = (
            "final_package_binding" if row.source == "final_package_semantic_binding" else
            "inherited" if row.policy == "GROUP" else
            "explicit" if row.policy == "EXPLICIT" else
            "E5" if row.source == "multilingual_semantic_match" else
            "lexical" if row.source == "lexical_semantic_match" else "abstention"
        )
        chosen = row.policy != "FALLBACK"
        reason = None if chosen else decision.get("reason") or "no_semantic_binding"
        if not chosen and reason == "accepted":
            reason = "joint_assignment_collision_or_invalid_window"
        if (
            not chosen
            and self.diagnostics.get("runtime_failure_count")
            and bool(decision.get("semantic_text"))
            and reason not in {"missing_semantic_metadata", "no_semantic_binding"}
        ):
            reason = "semantic_runtime_unavailable"
        details = {
            **decision, "beat_id": beat.id, "asset_id": row.asset_id,
            "semantic_unit_id": row.semantic_unit_id,
            "semantic_text": decision.get("semantic_text") or (
                self._semantic_query(entity, None, beat) if entity else ""
            ),
            "chosen_phrase": row.trigger_text if chosen else None,
            "source": source, "reason": reason,
            "spoken_start": row.spoken_start, "spoken_end": row.spoken_end,
        }
        for name in ("score", "runner_up_score", "margin", "phrase_index"):
            details.setdefault(name, None)
        if chosen:
            details["score"] = row.confidence
            for evidence in row.evidence:
                if evidence.startswith("phrase_index="):
                    details["phrase_index"] = int(evidence.split("=", 1)[1])
        self.diagnostics["assets"].append(details)
        row.evidence.append("semantic_match_diagnostic:" + json.dumps(
            details, ensure_ascii=False, sort_keys=True, allow_nan=False,
        ))
        _LOG.info("Story semantic asset: %s", json.dumps(details, ensure_ascii=False))

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
        asset_level_bindings = (
            package.semantic_bindings.get("schema_name")
            == "HEXA_ASSET_LEVEL_SEMANTIC_BINDINGS"
        )
        entities = self._ordered_entities(beat)
        words = self._beat_words(transcript, scene, beat)
        candidates = self._phrase_candidates(words, package.script)
        self._eligible_asset_ids.update(
            asset.id for asset in assets
            if asset.can_animate_independently
            and (asset.role or "").casefold() not in {"background", "decorative"}
        )
        asset_by_id = {asset.id: asset for asset in assets}
        if asset_level_bindings:
            activations = self._asset_level_binding_activations(
                package=package,
                transcript=transcript,
                scene=scene,
                assets=assets,
                beat=beat,
                semantic_map=semantic_map,
                binding_confidence=binding.binding_confidence,
            )
        else:
            activations = self._uniform_scene_binding_activations(
                package=package,
                transcript=transcript,
                scene=scene,
                assets=assets,
                beat=beat,
            )
        used_assets: set[str] = {row.asset_id for row in activations}
        options: list[tuple[StoryEntity, VisualAsset, list[AssetActivation]]] = []

        # Asset-level Final Packages are the semantic authority. Once present, do not
        # silently run a second semantic matcher for cutouts that the package did not
        # bind. Unmapped cutouts remain conservative/family-inherited instead of being
        # assigned a narration meaning by guesswork. Legacy packages keep the existing
        # entity/E5/lexical path unchanged.
        if not asset_level_bindings:
            for entity in entities:
                asset = asset_by_id.get(semantic_map.get(entity.unit_id, ""))
                if asset is None:
                    continue
                if asset.id in used_assets:
                    continue
                if asset.parent_asset_id and not asset.can_animate_independently:
                    continue
                if (entity.role or "").upper() in {"DECORATIVE", "BACKGROUND"}:
                    continue
                explicit = self._explicit_activation(
                    entity=entity, asset=asset, words=words, script=package.script,
                    scene=scene, beat=beat,
                )
                ranked = [explicit] if explicit else self._semantic_options(
                    entity=entity,
                    asset=asset,
                    query=self._semantic_query(entity, asset, beat),
                    candidates=candidates,
                    beat=beat,
                )
                options.append((entity, asset, ranked))

            edges = []
            for order, (entity, asset, ranked) in enumerate(options):
                for row in ranked:
                    edges.append((row, entity, asset, order))
            edges.sort(key=lambda item: (
                item[0].policy != "EXPLICIT", -item[0].confidence,
                (item[1].role or "").upper() != "PRIMARY",
                item[0].spoken_start, len((item[0].trigger_text or "").split()),
                item[3], item[2].id,
            ))
            used_units: set[str] = set()
            for row, entity, asset, _order in edges:
                if entity.unit_id in used_units or asset.id in used_assets:
                    continue
                if any(self._overlapping_anchors(row, chosen) for chosen in activations):
                    continue
                activations.append(row)
                used_units.add(entity.unit_id)
                used_assets.add(asset.id)

            self._repair_early_completion(activations, options, beat)

        by_asset = {row.asset_id: row for row in activations}
        pending = sorted(assets, key=lambda asset: asset.id)
        for _ in range(len(assets)):
            changed = False
            for asset in pending:
                if asset.id in by_asset:
                    continue
                parent = by_asset.get(asset.parent_asset_id or "")
                if (
                    parent is None
                    and not asset.parent_asset_id
                    and asset.asset_family_id
                    and (not asset.can_animate_independently or asset.render_as_family_canvas)
                ):
                    family = [
                        row for row in by_asset.values()
                        if row.policy != "GROUP"
                        and asset_by_id[row.asset_id].asset_family_id == asset.asset_family_id
                    ]
                    if len(family) == 1:
                        parent = family[0]
                if parent is None:
                    continue
                inherited = parent.model_copy(update={
                    "asset_id": asset.id,
                    "policy": "GROUP",
                    "confidence": min(0.78, parent.confidence),
                    "source": "parent_semantic_anchor",
                    "evidence": ["inherits_parent_semantic_time"],
                })
                activations.append(inherited)
                by_asset[asset.id] = inherited
                changed = True
            if not changed:
                break

        if asset_level_bindings and beat.id not in self._identity_incomplete_beats:
            derived_support = self._single_group_support_activations(
                package=package,
                scene=scene,
                assets=assets,
                beat=beat,
                already_bound=by_asset,
            )
            activations.extend(derived_support)
            by_asset.update({row.asset_id: row for row in derived_support})

        mapped_unit_by_asset = {asset_id: unit_id for unit_id, asset_id in semantic_map.items()}
        for asset in sorted(assets, key=lambda asset: asset.id):
            if asset.id not in by_asset:
                unit_id = (
                    mapped_unit_by_asset.get(asset.id)
                    if asset_level_bindings
                    else next(
                        (entity.unit_id for entity, bound, _ in options if bound.id == asset.id),
                        None,
                    )
                )
                activations.append(AssetActivation(
                    asset_id=asset.id,
                    semantic_unit_id=unit_id,
                    confidence=0.0,
                    source="semantic_abstention",
                    policy="FALLBACK",
                    evidence=["no_confident_final_package_binding", "SAFE_ABSTENTION"],
                ))

        return sorted(
            activations,
            key=lambda row: (
                row.spoken_start if row.spoken_start is not None else math.inf,
                row.semantic_group_id or "",
                row.sequence_order if row.sequence_order is not None else 10_000,
                row.policy == "GROUP",
                row.asset_id,
            ),
        )

    def _asset_level_binding_activations(
        self,
        *,
        package: PackageModel,
        transcript: Transcript,
        scene: SceneSource,
        assets: list[VisualAsset],
        beat: StoryBeat,
        semantic_map: dict[str, str],
        binding_confidence: float,
    ) -> list[AssetActivation]:
        scenes = package.semantic_bindings.get("scenes")
        if not isinstance(scenes, list):
            return []
        scene_binding = next(
            (
                row for row in scenes
                if isinstance(row, dict) and row.get("scene_id") == scene.id
            ),
            None,
        )
        if scene_binding is None:
            return []
        binding_assets = scene_binding.get("assets")
        if not isinstance(binding_assets, list) or not binding_assets:
            return []
        groups = {
            str(row.get("semantic_group_id")): row
            for row in scene_binding.get("semantic_groups", [])
            if isinstance(row, dict) and row.get("semantic_group_id")
        }
        asset_by_id = {asset.id: asset for asset in assets}
        identity = self.identity_binder.bind(
            scene=scene,
            semantic_assets=[row for row in binding_assets if isinstance(row, dict)],
            assets=assets,
        )
        if identity.has_incomplete_locator_binding:
            self._identity_incomplete_beats.add(beat.id)
        for semantic_id in sorted(identity.locator_semantic_ids):
            identity_matches = identity.matches_for(semantic_id)
            primary_match = identity_matches[0] if identity_matches else None
            self.diagnostics["visual_identity"].append({
                "beat_id": beat.id,
                "scene_id": scene.id,
                "semantic_asset_id": semantic_id,
                "real_asset_id": (
                    primary_match.real_asset_id
                    if len(identity_matches) == 1
                    else None
                ),
                "real_asset_ids": [row.real_asset_id for row in identity_matches],
                "member_count": len(identity_matches),
                "source": primary_match.source if primary_match is not None else "abstention",
                "score": primary_match.score if primary_match is not None else None,
                "runner_up_score": (
                    primary_match.runner_up_score if primary_match is not None else None
                ),
                "margin": primary_match.margin if primary_match is not None else None,
                "reason": (
                    "accepted_multi_cutout_visual_unit"
                    if len(identity_matches) > 1
                    else "accepted"
                    if primary_match is not None
                    else "ambiguous_or_missing_real_cutout_geometry"
                ),
            })
        identity_claimed_real: dict[str, str] = {}
        for semantic_id in identity.locator_semantic_ids:
            for match in identity.matches_for(semantic_id):
                identity_claimed_real[match.real_asset_id] = semantic_id
        audio_start = beat.audio_start if beat.audio_start is not None else beat.start
        audio_end = beat.audio_end if beat.audio_end is not None else beat.end
        tolerance = 0.025
        phrase_cache: dict[str, tuple[int, int, float, float] | None] = {}
        candidates_by_real: dict[str, list[AssetActivation]] = {}

        for row in binding_assets:
            if not isinstance(row, dict):
                continue
            semantic_id = str(row.get("asset_id") or "").strip()
            phrase = str(row.get("script_text") or "").strip()
            binding_type = str(row.get("binding_type") or "").upper()
            if not semantic_id or not phrase or binding_type == "AMBIGUOUS":
                continue
            identity_matches = identity.matches_for(semantic_id)
            resolved_assets: list[tuple[VisualAsset, Any]] = []
            if semantic_id in identity.locator_semantic_ids:
                # A visual locator is explicit identity evidence. It may describe one
                # real cutout or one authored visual unit composed of several detached
                # cutouts. If neither can be resolved conservatively, abstain instead
                # of falling back to size/order heuristics that can swap meanings.
                if not identity_matches:
                    continue
                for identity_match in identity_matches:
                    asset = asset_by_id.get(identity_match.real_asset_id)
                    if (
                        asset is None
                        or not asset.can_animate_independently
                        or (asset.role or "").casefold() in {"background", "decorative"}
                    ):
                        continue
                    resolved_assets.append((asset, identity_match))
            else:
                real_id = semantic_map.get(semantic_id)
                if real_id is None and semantic_id in asset_by_id:
                    real_id = semantic_id
                claimed_by = identity_claimed_real.get(real_id or "")
                if claimed_by is not None and claimed_by != semantic_id:
                    continue
                asset = asset_by_id.get(real_id or "")
                if (
                    asset is None
                    or not asset.can_animate_independently
                    or (asset.role or "").casefold() in {"background", "decorative"}
                ):
                    continue
                resolved_assets.append((asset, None))
            if not resolved_assets:
                continue

            timing = phrase_cache.get(phrase)
            if phrase not in phrase_cache:
                span = self._binding_phrase_span(package.script, scene, phrase)
                if span is None:
                    phrase_cache[phrase] = None
                    continue
                char_start, char_end = span
                phrase_words = [
                    word for word in transcript.words
                    if word.char_start is not None
                    and word.char_end is not None
                    and word.char_end > char_start
                    and word.char_start < char_end
                ]
                if not phrase_words:
                    phrase_cache[phrase] = None
                    continue
                spoken_start = phrase_words[0].start
                spoken_end = phrase_words[-1].end
                if (
                    spoken_start < audio_start - tolerance
                    or spoken_end > audio_end + tolerance
                    or spoken_end <= spoken_start
                ):
                    phrase_cache[phrase] = None
                    continue
                timing = (char_start, char_end, spoken_start, spoken_end)
                phrase_cache[phrase] = timing
            if timing is None:
                continue
            char_start, char_end, spoken_start, spoken_end = timing
            group_id = str(row.get("semantic_group_id") or "").strip() or None
            group = groups.get(group_id or "", {})
            group_policy = str(
                group.get("animation_policy") or "SEQUENTIAL_WITHIN_PHRASE"
            )
            sequence_order = row.get("sequence_order")
            semantic_confidence = float(row.get("confidence", 0.0))
            policy = "EXPLICIT" if binding_type == "EXPLICIT" else "SEMANTIC"

            for asset, identity_match in resolved_assets:
                if identity_match is not None:
                    confidence = min(semantic_confidence, identity_match.score)
                else:
                    confidence = min(
                        semantic_confidence, max(0.0, binding_confidence)
                    )
                activation = AssetActivation(
                    asset_id=asset.id,
                    semantic_unit_id=semantic_id,
                    trigger_text=phrase,
                    trigger_char_start=char_start,
                    trigger_char_end=char_end,
                    spoken_start=spoken_start,
                    spoken_end=spoken_end,
                    confidence=confidence,
                    source="final_package_semantic_binding",
                    policy=policy,
                    semantic_group_id=group_id,
                    sequence_order=(
                        int(sequence_order) if sequence_order is not None else None
                    ),
                    binding_type=binding_type,
                    semantic_parent_id=(
                        str(row.get("parent_asset_id"))
                        if row.get("parent_asset_id") is not None
                        else None
                    ),
                    group_animation_policy=group_policy,
                    evidence=[
                        "asset_level_final_package_binding",
                        "exact_final_package_script_text",
                        f"semantic_intent={semantic_id}",
                        f"semantic_group={group_id}",
                        f"sequence_order={sequence_order}",
                        f"binding_type={binding_type}",
                        f"binder_confidence={binding_confidence:.6f}",
                        *(
                            [
                                "visual_identity_binding",
                                f"visual_identity_source={identity_match.source}",
                                f"visual_identity_score={identity_match.score:.6f}",
                                f"visual_identity_runner_up={identity_match.runner_up_score if identity_match.runner_up_score is not None else 'none'}",
                                f"visual_identity_margin={identity_match.margin if identity_match.margin is not None else 'none'}",
                                *(
                                    ["visual_identity_multi_cutout_member"]
                                    if identity_match.source == "visual_locator_multi"
                                    else []
                                ),
                            ]
                            if identity_match is not None
                            and semantic_id in identity.locator_semantic_ids
                            else []
                        ),
                    ],
                )
                candidates_by_real.setdefault(asset.id, []).append(activation)

        output: list[AssetActivation] = []
        for real_id, rows in sorted(candidates_by_real.items()):
            if len(rows) == 1:
                chosen = rows[0]
            else:
                signatures = {
                    (
                        row.trigger_char_start, row.trigger_char_end,
                        row.semantic_group_id, row.sequence_order,
                    )
                    for row in rows
                }
                if len(signatures) != 1:
                    self._decisions[(beat.id, real_id)] = {
                        "reason": "ambiguous_semantic_intent_mapping",
                        "candidate_count": len(rows),
                    }
                    continue
                chosen = max(rows, key=lambda row: (row.confidence, row.semantic_unit_id or ""))
                chosen.evidence.append("coalesced_equivalent_semantic_intents")
            self._decisions[(beat.id, real_id)] = {
                "semantic_text": chosen.trigger_text,
                "reason": "accepted_asset_level_final_package_binding",
                "score": chosen.confidence,
                "runner_up_score": None,
                "margin": None,
                "phrase_index": None,
                "candidate_phrase": chosen.trigger_text,
                "semantic_group_id": chosen.semantic_group_id,
                "sequence_order": chosen.sequence_order,
            }
            output.append(chosen)
        return output

    def _single_group_support_activations(
        self,
        *,
        package: PackageModel,
        scene: SceneSource,
        assets: list[VisualAsset],
        beat: StoryBeat,
        already_bound: dict[str, AssetActivation],
    ) -> list[AssetActivation]:
        """Bind extra real cutouts only when their scene-level group is unambiguous.

        Asset-level metadata describes semantic intents, not segmentation cardinality.
        A single intent or group may therefore correspond to several real cutouts. When
        exactly one semantic group exists in the scene, extra independent cutouts can
        safely inherit that group's spoken phrase without guessing between meanings.
        They are appended after authored sequence orders in deterministic visual-weight
        order. Multi-group scenes remain abstentions unless explicitly mapped.
        """
        scenes = package.semantic_bindings.get("scenes")
        if not isinstance(scenes, list):
            return []
        scene_binding = next(
            (
                row for row in scenes
                if isinstance(row, dict) and row.get("scene_id") == scene.id
            ),
            None,
        )
        if scene_binding is None:
            return []
        groups = [
            row for row in scene_binding.get("semantic_groups", [])
            if isinstance(row, dict)
        ]
        if len(groups) != 1:
            return []
        group = groups[0]
        if group.get("animation_policy", "SEQUENTIAL_WITHIN_PHRASE") != (
            "SEQUENTIAL_WITHIN_PHRASE"
        ):
            return []
        group_id = str(group.get("semantic_group_id") or "").strip()
        if not group_id:
            return []
        anchors = [
            row for row in already_bound.values()
            if row.semantic_group_id == group_id
            and row.source == "final_package_semantic_binding"
            and row.spoken_start is not None
            and row.spoken_end is not None
        ]
        if not anchors:
            return []
        anchor = min(
            anchors,
            key=lambda row: (
                row.sequence_order if row.sequence_order is not None else 10_000,
                row.asset_id,
            ),
        )
        max_order = max(
            (row.sequence_order or 0)
            for row in anchors
        )
        unbound = [
            asset for asset in assets
            if asset.id not in already_bound
            and asset.can_animate_independently
            and (asset.role or "").casefold() not in {"background", "decorative"}
        ]
        unbound.sort(key=lambda asset: (-self._asset_visual_weight(asset), asset.id))

        output: list[AssetActivation] = []
        for offset, asset in enumerate(unbound, start=1):
            order = max_order + offset
            semantic_unit_id = f"{group_id}:unbound-support:{offset}"
            row = AssetActivation(
                asset_id=asset.id,
                semantic_unit_id=semantic_unit_id,
                trigger_text=anchor.trigger_text,
                trigger_char_start=anchor.trigger_char_start,
                trigger_char_end=anchor.trigger_char_end,
                spoken_start=anchor.spoken_start,
                spoken_end=anchor.spoken_end,
                confidence=min(0.55, anchor.confidence),
                source="final_package_scene_support",
                policy="SEMANTIC",
                semantic_group_id=group_id,
                sequence_order=order,
                binding_type="SUPPORT",
                group_animation_policy="SEQUENTIAL_WITHIN_PHRASE",
                evidence=[
                    "single_unambiguous_semantic_group",
                    "derived_unbound_cutout_support_tail",
                    f"semantic_group={group_id}",
                    f"sequence_order={order}",
                ],
            )
            self._decisions[(beat.id, asset.id)] = {
                "semantic_text": anchor.trigger_text,
                "reason": "accepted_single_group_unbound_support",
                "score": row.confidence,
                "runner_up_score": None,
                "margin": None,
                "phrase_index": None,
                "candidate_phrase": anchor.trigger_text,
                "semantic_group_id": group_id,
                "sequence_order": order,
            }
            output.append(row)
        return output

    @staticmethod
    def _asset_visual_weight(asset: VisualAsset) -> float:
        if asset.source_area_ratio is not None:
            return float(asset.source_area_ratio)
        if (
            asset.source_bbox
            and asset.source_canvas_width
            and asset.source_canvas_height
        ):
            _x, _y, width, height = asset.source_bbox
            return (width * height) / (asset.source_canvas_width * asset.source_canvas_height)
        return 0.0

    def _uniform_scene_binding_activations(
        self,
        *,
        package: PackageModel,
        transcript: Transcript,
        scene: SceneSource,
        assets: list[VisualAsset],
        beat: StoryBeat,
    ) -> list[AssetActivation]:
        phrase = self._uniform_scene_binding_phrase(package, scene.id)
        if phrase is None:
            return []
        span = self._binding_phrase_span(package.script, scene, phrase)
        if span is None:
            return []
        char_start, char_end = span
        words = [
            word for word in transcript.words
            if word.char_start is not None
            and word.char_end is not None
            and word.char_end > char_start
            and word.char_start < char_end
        ]
        if not words:
            return []

        spoken_start = words[0].start
        spoken_end = words[-1].end
        audio_start = beat.audio_start if beat.audio_start is not None else beat.start
        audio_end = beat.audio_end if beat.audio_end is not None else beat.end
        tolerance = 0.025
        if (
            spoken_start < audio_start - tolerance
            or spoken_end > audio_end + tolerance
            or spoken_end <= spoken_start
        ):
            return []

        semantic_unit_id = f"semantic_bindings:{scene.id}"
        output: list[AssetActivation] = []
        for asset in sorted(assets, key=lambda row: row.id):
            if (
                not asset.can_animate_independently
                or (asset.role or "").casefold() in {"background", "decorative"}
            ):
                continue
            self._decisions[(beat.id, asset.id)] = {
                "semantic_text": phrase,
                "reason": "accepted_final_package_semantic_binding",
                "score": 1.0,
                "runner_up_score": None,
                "margin": None,
                "phrase_index": None,
                "candidate_phrase": phrase,
            }
            output.append(AssetActivation(
                asset_id=asset.id,
                semantic_unit_id=semantic_unit_id,
                trigger_text=phrase,
                trigger_char_start=char_start,
                trigger_char_end=char_end,
                spoken_start=spoken_start,
                spoken_end=spoken_end,
                confidence=1.0,
                source="final_package_semantic_binding",
                policy="EXPLICIT",
                evidence=[
                    "semantic_bindings_scene_uniform_phrase",
                    "exact_final_package_script_text",
                ],
            ))
        return output

    @staticmethod
    def _uniform_scene_binding_phrase(package: PackageModel, scene_id: str) -> str | None:
        scenes = package.semantic_bindings.get("scenes")
        if not isinstance(scenes, list):
            return None
        row = next(
            (
                item for item in scenes
                if isinstance(item, dict) and item.get("scene_id") == scene_id
            ),
            None,
        )
        if row is None:
            return None
        assets = row.get("assets")
        if not isinstance(assets, list) or not assets:
            return None
        phrases = [
            str(asset.get("script_text") or "").strip()
            for asset in assets
            if isinstance(asset, dict)
        ]
        if len(phrases) != len(assets) or any(not phrase for phrase in phrases):
            return None
        normalized = {
            HybridSemanticTextScorer._normalize(phrase)
            for phrase in phrases
        }
        return phrases[0] if len(normalized) == 1 else None

    @staticmethod
    def _binding_phrase_span(
        script: str | None,
        scene: SceneSource,
        phrase: str,
    ) -> tuple[int, int] | None:
        if not script or scene.script_char_start is None or scene.script_char_end is None:
            return None
        scene_start = max(0, scene.script_char_start)
        scene_end = min(len(script), scene.script_char_end + 1)
        if scene_end <= scene_start:
            return None
        haystack = script[scene_start:scene_end]

        stripped = haystack.strip()
        if stripped == phrase.strip():
            local_start = haystack.find(stripped)
            return scene_start + local_start, scene_start + local_start + len(stripped)

        matches: list[int] = []
        cursor = 0
        while True:
            found = haystack.find(phrase, cursor)
            if found < 0:
                break
            matches.append(found)
            cursor = found + max(1, len(phrase))
        if len(matches) != 1:
            return None
        absolute_start = scene_start + matches[0]
        return absolute_start, absolute_start + len(phrase)

    @staticmethod
    def _repair_early_completion(activations, options, beat: StoryBeat) -> None:
        if not activations:
            return
        upper = min(beat.end, beat.audio_end if beat.audio_end is not None else beat.end)
        lower = max(beat.start, beat.audio_start if beat.audio_start is not None else beat.start)
        last_end = max(row.spoken_end for row in activations)
        if upper - last_end <= (upper - lower) * 0.20:
            return
        # Only move to a near-equivalent, already accepted spoken meaning. Explicit
        # package triggers never move. No artificial delay or phrase stretching.
        alternatives = []
        for _entity, _asset, ranked in options:
            for candidate in ranked:
                for index, current in enumerate(activations):
                    if (current.policy == "SEMANTIC" and candidate.asset_id == current.asset_id
                            and candidate.semantic_unit_id == current.semantic_unit_id
                            and candidate.confidence >= current.confidence - 0.03
                            and candidate.spoken_end > last_end
                            and not any(SemanticActivationPlanner._overlapping_anchors(candidate, row)
                                        for j, row in enumerate(activations) if j != index)):
                        alternatives.append((index, candidate))
        if alternatives:
            index, chosen = min(alternatives, key=lambda item: (
                -item[1].spoken_end, -item[1].confidence, item[1].asset_id,
            ))
            activations[index] = chosen.model_copy(update={
                "evidence": chosen.evidence + ["early_completion_reassigned_to_confident_late_phrase"],
            })

    @staticmethod
    def _overlapping_anchors(left: AssetActivation, right: AssetActivation) -> bool:
        if None in (left.spoken_start, left.spoken_end, right.spoken_start, right.spoken_end):
            return False
        overlap = min(left.spoken_end, right.spoken_end) - max(left.spoken_start, right.spoken_start)
        shortest = min(left.spoken_end - left.spoken_start, right.spoken_end - right.spoken_start)
        return overlap > max(0.0, shortest * 0.5)

    def _semantic_options(
        self, *, entity: StoryEntity, asset: VisualAsset, query: str,
        candidates: list[_PhraseCandidate], beat: StoryBeat,
    ) -> list[AssetActivation]:
        decision = {"semantic_text": query, "reason": "missing_semantic_metadata",
                    "score": None, "runner_up_score": None, "margin": None, "phrase_index": None}
        self._decisions[(beat.id, asset.id)] = decision
        if not query:
            return []
        speech_upper = beat.audio_end if beat.audio_end is not None else beat.end
        viable = [row for row in candidates
                  if math.isfinite(row.spoken_start) and math.isfinite(row.spoken_end)
                  and beat.start <= row.spoken_start < row.spoken_end <= speech_upper]
        if not viable:
            decision["reason"] = "no_aligned_phrase_candidates"
            return []
        try:
            scores, semantic_used = self.scorer.score(query, [row.text for row in viable])
        finally:
            self._runtime_diagnostics()
        ranked = sorted(
            (index for index, score in enumerate(scores[:len(viable)]) if math.isfinite(score)),
            key=lambda index: (-scores[index], viable[index].token_count, viable[index].spoken_start),
        )
        if not ranked:
            decision["reason"] = "nonfinite_or_missing_scores"
            return []
        best = scores[ranked[0]]
        top = viable[ranked[0]]
        # Nested ngrams are variants of one spoken occurrence, not independent
        # competing meanings. A repeated phrase elsewhere remains a competitor.
        def distinct(row):
            overlap = min(row.spoken_end, top.spoken_end) - max(row.spoken_start, top.spoken_start)
            shortest = min(row.spoken_end - row.spoken_start, top.spoken_end - top.spoken_start)
            return overlap <= shortest * 0.5
        runner = next((i for i in ranked[1:] if distinct(viable[i])), None)
        second = scores[runner] if runner is not None else 0.0
        margin = best - second
        decision.update(score=best, runner_up_score=second, margin=margin,
                        phrase_index=candidates.index(top), candidate_phrase=top.text)
        accepted = (
            semantic_used and best >= self._MIN_SEMANTIC_SCORE
            and margin >= self._MIN_SEMANTIC_MARGIN
        ) or (not semantic_used and best >= self._MIN_LEXICAL_SCORE
              and margin >= self._MIN_LEXICAL_MARGIN)
        decision["reason"] = "accepted" if accepted else (
            "ambiguous_phrase_candidates" if best >= (
                self._MIN_SEMANTIC_SCORE if semantic_used else self._MIN_LEXICAL_SCORE
            ) else "score_below_threshold"
        )
        if not accepted:
            return []
        result: list[AssetActivation] = []
        for index in ranked:
            score, chosen = scores[index], viable[index]
            if result and (not semantic_used or score < max(0.80, best - 0.08)):
                continue
            activation = AssetActivation(
                asset_id=asset.id, semantic_unit_id=entity.unit_id,
                trigger_text=chosen.text, trigger_char_start=chosen.char_start,
                trigger_char_end=chosen.char_end, spoken_start=chosen.spoken_start,
                spoken_end=chosen.spoken_end, confidence=max(0.0, min(1.0, score)),
                source="multilingual_semantic_match" if semantic_used else "lexical_semantic_match",
                policy="SEMANTIC",
                evidence=[f"score={score:.3f}", f"margin={margin:.3f}", f"query={query}",
                          f"phrase_index={candidates.index(chosen)}",
                          "scene_joint_assignment"],
            )
            # Prune overlapping variants of the same phrase before assignment.
            if any(self._overlapping_anchors(activation, row) for row in result):
                continue
            result.append(activation)
            if len(result) >= self._MAX_ASSIGNMENT_CANDIDATES:
                break
        return result

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
            speech_upper = beat.audio_end if beat.audio_end is not None else beat.end
            if (not math.isfinite(start) or not math.isfinite(span_words[-1].end)
                    or start < beat.start or span_words[-1].end > speech_upper
                    or span_words[-1].end <= start):
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
        seen: set[tuple[float, float, str]] = set()
        for start_index in range(len(words)):
            for length in range(1, min(self._MAX_NGRAM, len(words) - start_index) + 1):
                rows = words[start_index:start_index + length]
                text = self._text_for_words(rows, script)
                key = (rows[0].start, rows[-1].end, text)
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
    def _semantic_query(
        entity: StoryEntity, asset: VisualAsset | None, beat: StoryBeat | None = None,
    ) -> str:
        del asset  # Extraction role/filename is not evidence of semantic meaning.
        values: list[str] = []
        metadata = entity.package_metadata
        for container in (metadata, metadata.get("semantic_context")):
            if not isinstance(container, dict):
                continue
            for key in ("description", "label", "visual_label", "meaning", "concept"):
                value = container.get(key)
                if isinstance(value, str) and value.strip():
                    values.append(value.strip())

        # A package may keep unit IDs structural while authoring the real visual
        # meaning at scene level. Only the primary/group entity inherits that scene
        # description so support assets do not all chase the same narration phrase.
        context = beat.semantic_context if beat is not None else None
        if context is not None and (
            (entity.role or "").upper() == "PRIMARY"
            or (entity.entity_type or "").upper() == "GROUP"
        ):
            # Scene visual concept is authored visual evidence. Scene purpose may echo
            # narration verbatim and would let E5 "match" text to itself rather than
            # understand the visual meaning, so it is intentionally excluded here.
            value = context.scene_visual_concept
            if isinstance(value, str) and value.strip():
                values.append(value.strip())

        # Structural semantic names are only a last resort. Rich visual metadata should
        # not be diluted by identifiers such as scene_003 or white_hat_scene_004.
        if not values and entity.semantic_name:
            values.append(entity.semantic_name.replace("_", " ").strip())
        if not values and entity.narrative_function:
            value = entity.narrative_function.replace("_", " ").strip()
            if len(value.split()) > 1:
                values.append(value)
        structural = {(entity.entity_type or "").casefold(), (entity.role or "").casefold(),
                      ""}
        return " ; ".join(dict.fromkeys(value for value in values
                                        if value and value.casefold() not in structural))

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
                and word.char_start <= trigger.global_char_end
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
