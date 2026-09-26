import json

import pytest

from app.models import (
    SceneSource, SemanticEventProxy, StoryBeat, StoryEntity, StorySemanticContext,
    StoryTrigger, TranscriptWord, VisualAsset,
)
from app.story.activation import HybridSemanticTextScorer, SemanticActivationPlanner
from app.story.binding import SemanticAssetBinder
from app.story.windows import StoryAssetActivation
from test_story_activation_windows import Scorer, scene_case


def test_cross_language_meaning_uses_semantic_interface_and_aligned_timing(tmp_path):
    package, transcript, assets, beat = scene_case(tmp_path, 2)
    beat.semantic_context.entities = [StoryEntity(
        unit_id=assets[0].id, package_metadata={"description": "security vulnerability"},
    )]
    transcript.words[0].text = "نقاط الضعف"
    scorer = Scorer({"security vulnerability": {"نقاط الضعف": 0.93}})
    planner = SemanticActivationPlanner(scorer=scorer)
    result = planner.enrich(package, transcript, assets, [beat])[0]
    row = result.asset_activations[0]
    assert scorer.calls == 1
    assert row.trigger_text == "نقاط الضعف"
    assert row.spoken_start == transcript.words[0].start
    assert row.spoken_end == transcript.words[0].end
    assert row.source == "multilingual_semantic_match"
    diag = planner.diagnostics["assets"][0]
    assert diag["semantic_text"] == "security vulnerability"
    assert diag["source"] == "E5" and diag["score"] == 0.93
    assert diag["margin"] > 0.015 and diag["phrase_index"] == 0
    assert planner.diagnostics["trusted_count"] == 1
    persisted = next(s for s in row.evidence if s.startswith("semantic_match_diagnostic:"))
    assert json.loads(persisted.split(":", 1)[1]) == diag


def test_high_score_cannot_bypass_ambiguity_margin(tmp_path):
    package, transcript, assets, beat = scene_case(tmp_path, 2)
    scorer = Scorer({"concept00": {"concept00": 0.96, "concept01": 0.955}, "concept01": {}})
    planner = SemanticActivationPlanner(scorer=scorer)
    result = planner.enrich(package, transcript, assets, [beat])[0]
    assert all(r.activation_policy == "SAFE_ABSTENTION" for r in result.asset_activations)
    assert planner.diagnostics["assets"][0]["reason"] == "ambiguous_phrase_candidates"


def test_overlapping_ngram_variant_does_not_hide_clear_margin(tmp_path):
    package, transcript, assets, beat = scene_case(tmp_path, 2)
    scorer = Scorer({"concept00": {"concept00": 0.9, "concept00 concept01": 0.899},
                     "concept01": {}})
    result = SemanticActivationPlanner(scorer=scorer).enrich(package, transcript, assets, [beat])[0]
    assert result.asset_activations[0].trigger_text == "concept00"


def test_missing_meaning_does_not_use_filename_or_generic_role(tmp_path):
    package, transcript, assets, beat = scene_case(tmp_path, 1)
    beat.semantic_context.entities[0] = StoryEntity(unit_id=assets[0].id, entity_type="ICON")
    scorer = Scorer()
    planner = SemanticActivationPlanner(scorer=scorer)
    result = planner.enrich(package, transcript, assets, [beat])[0]
    assert scorer.calls == 0
    assert result.asset_activations[0].activation_policy == "SAFE_ABSTENTION"
    assert planner.diagnostics["assets"][0]["reason"] == "missing_semantic_metadata"


def test_repeated_phrase_occurrences_are_ambiguous_without_explicit_trigger(tmp_path):
    package, transcript, assets, beat = scene_case(tmp_path, 3)
    transcript.words[2].text = "concept00"
    planner = SemanticActivationPlanner(scorer=Scorer())
    result = planner.enrich(package, transcript, assets, [beat])[0]
    row = next(r for r in result.asset_activations if r.asset_id == "concept00")
    assert row.activation_policy == "SAFE_ABSTENTION"
    diag = next(d for d in planner.diagnostics["assets"] if d["asset_id"] == row.asset_id)
    assert diag["margin"] == 0


def test_explicit_occurrence_selects_second_aligned_phrase(tmp_path):
    package, transcript, assets, beat = scene_case(tmp_path, 3)
    package.script = "again next again"
    transcript.words = [
        TranscriptWord(text="again", start=0, end=1, char_start=0, char_end=5),
        TranscriptWord(text="next", start=4, end=5, char_start=6, char_end=10),
        TranscriptWord(text="again", start=8, end=9, char_start=11, char_end=16),
    ]
    beat.semantic_context.entities[0].appear_trigger = StoryTrigger(phrase="again", occurrence_in_scene=2)
    planner = SemanticActivationPlanner(scorer=Scorer())
    result = planner.enrich(package, transcript, assets, [beat])[0]
    row = next(r for r in result.asset_activations if r.asset_id == "concept00")
    assert row.policy == "EXPLICIT" and row.spoken_start == 8


def test_explicit_asset_identity_outranks_geometry(tmp_path):
    package, _, assets, beat = scene_case(tmp_path, 2)
    package.scenes[0].units[0]["asset_id"] = assets[1].id
    package.scenes[0].units[1]["asset_id"] = assets[0].id
    binding = SemanticAssetBinder().bind(scene=package.scenes[0], assets=assets,
                                        beat=beat, action=beat.action)
    assert dict(binding.semantic_asset_map) == {"concept00": "concept01", "concept01": "concept00"}




def test_safe_abstention_blocks_heuristic_semantic_remap_but_proxy_is_allowed(tmp_path):
    scene = SceneSource(
        id="scene",
        image_path=tmp_path / "scene.png",
        order=0,
        units=[
            {"unit_id": "trusted-unit", "type": "VISUAL_ASSET_INTENT", "role": "PRIMARY"},
            {"unit_id": "abstained-unit", "type": "VISUAL_ASSET_INTENT", "role": "SUPPORTING"},
            {"unit_id": "proxy-unit", "type": "VISUAL_ASSET_INTENT", "role": "SUPPORTING"},
        ],
    )
    assets = [
        VisualAsset(
            id="real-a", scene_id=scene.id, role="support",
            image_path=scene.image_path, extraction_method="test", source_area_ratio=0.4,
        ),
        VisualAsset(
            id="real-b", scene_id=scene.id, role="support",
            image_path=scene.image_path, extraction_method="test", source_area_ratio=0.3,
        ),
    ]
    beat = StoryBeat(
        id="beat", scene_id=scene.id, start=0.0, end=2.0, narration="x", action="EXPLAIN",
        asset_activations=[
            StoryAssetActivation(
                asset_id="real-a", semantic_unit_id="trusted-unit",
                confidence=0.99, source="final_package_semantic_binding", policy="EXPLICIT",
                phrase_start=0.1, phrase_end=0.8, reveal_start=0.1, semantic_peak=0.4,
                settle_at=0.7, activation_policy="OWN_WINDOW",
            ),
            StoryAssetActivation(
                asset_id="real-b", semantic_unit_id="abstained-unit",
                confidence=0.0, source="semantic_abstention", policy="FALLBACK",
                activation_policy="SAFE_ABSTENTION",
            ),
        ],
        semantic_event_proxies=[
            SemanticEventProxy(
                asset_id="real-a", semantic_unit_id="proxy-unit", semantic_group_id="G1",
                semantic_event_id="E2", semantic_event_order=2,
                semantic_event_roles=["LEADER"], semantic_event_dependency_ids=["E1"],
                trigger_text="x", trigger_char_start=0, trigger_char_end=1,
                spoken_start=0.2, spoken_end=1.0, reveal_start=0.3, semantic_peak=0.5,
                settle_at=0.8, authority="FINAL_PACKAGE_GROUP_PROXY",
            )
        ],
    )

    binding = SemanticAssetBinder().bind(
        scene=scene, assets=assets, action=beat.action, beat=beat,
    )
    semantic_map = dict(binding.semantic_asset_map)

    assert semantic_map["trusted-unit"] == "real-a"
    assert semantic_map["proxy-unit"] == "real-a"
    assert "abstained-unit" not in semantic_map


def test_group_container_does_not_claim_cutout_before_visual_asset_intent(tmp_path):
    scene = SceneSource(
        id="scene",
        image_path=tmp_path / "scene.png",
        order=0,
        units=[
            {"unit_id": "group-container", "type": "GROUP", "role": "PRIMARY"},
            {"unit_id": "intent", "type": "VISUAL_ASSET_INTENT", "role": "SUPPORTING"},
        ],
    )
    asset = VisualAsset(
        id="real-asset",
        scene_id=scene.id,
        role="support",
        image_path=scene.image_path,
        extraction_method="test",
        source_area_ratio=0.3,
    )

    binding = SemanticAssetBinder().bind(
        scene=scene, assets=[asset], action="REVEAL", beat=None,
    )

    assert dict(binding.semantic_asset_map) == {"intent": "real-asset"}

def test_query_extracts_nested_metadata_without_structural_labels():
    entity = StoryEntity(unit_id="UNIT_42", entity_type="ICON", role="SUPPORTING",
                         package_metadata={"semantic_context": {"description": "an open book"}})
    assert SemanticActivationPlanner._semantic_query(entity, None) == "an open book"


def test_e5_scoring_path_is_primary_and_not_lexical(monkeypatch):
    scorer = HybridSemanticTextScorer("intfloat/multilingual-e5-small")
    calls = []
    def embeddings(query, candidates):
        calls.append((query, candidates))
        return [0.95, 0.50]
    monkeypatch.setattr(scorer, "_embedding_scores", embeddings)
    scores, used = scorer.score("security vulnerability", ["نقاط الضعف", "عبارة أخرى"])
    assert used and scores[0] > scores[1]
    assert calls == [("security vulnerability", ["نقاط الضعف", "عبارة أخرى"])]


def test_explicit_global_span_does_not_capture_next_word(tmp_path):
    package, transcript, assets, beat = scene_case(tmp_path, 2)
    package.script = "first next"
    transcript.words = [
        TranscriptWord(text="first", start=0.0, end=0.8, char_start=0, char_end=5),
        TranscriptWord(text="next", start=0.8, end=1.5, char_start=6, char_end=10),
    ]
    beat.start = 0.0
    beat.end = 0.9
    beat.audio_start = 0.0
    beat.audio_end = 0.8
    beat.semantic_context.entities = [StoryEntity(
        unit_id=assets[0].id,
        appear_trigger=StoryTrigger(
            phrase="first", occurrence_in_scene=1,
            global_char_start=0, global_char_end=5,
        ),
    )]
    beat.semantic_targets = [assets[0].id]
    result = SemanticActivationPlanner(scorer=Scorer()).enrich(
        package, transcript, assets, [beat],
    )[0]
    row = next(r for r in result.asset_activations if r.asset_id == assets[0].id)
    assert row.policy == "EXPLICIT"
    assert row.trigger_text == "first"
    assert row.spoken_end == pytest.approx(0.8)


def test_primary_group_query_uses_scene_visual_context_without_leaking_to_support():
    context = StorySemanticContext(
        scene_visual_concept="الباحث يكشف ثغرة صغيرة بعدسة أمنية",
        scene_purpose="عشان يكتشف نقاط الضعف",
    )
    beat = StoryBeat(
        id="b", scene_id="s", start=0, end=2, audio_start=0, audio_end=2,
        narration="عشان يكتشف نقاط الضعف", action="EXPLAIN", semantic_context=context,
    )
    primary = StoryEntity(
        unit_id="p", semantic_name="scene_003", entity_type="GROUP", role="PRIMARY",
    )
    support = StoryEntity(
        unit_id="s", semantic_name="security analyst", entity_type="CHARACTER", role="SUPPORTING",
    )
    primary_query = SemanticActivationPlanner._semantic_query(primary, None, beat)
    support_query = SemanticActivationPlanner._semantic_query(support, None, beat)
    assert primary_query == "الباحث يكشف ثغرة صغيرة بعدسة أمنية"
    assert "عشان يكتشف نقاط الضعف" not in primary_query
    assert "scene 003" not in primary_query
    assert support_query == "security analyst"



def test_runtime_failure_does_not_mask_missing_semantic_binding_reason(tmp_path):
    package, transcript, assets, beat = scene_case(tmp_path, 1)
    beat.semantic_context.entities = []
    scorer = HybridSemanticTextScorer(None, required=False)
    planner = SemanticActivationPlanner(scorer=scorer)
    result = planner.enrich(package, transcript, assets, [beat])[0]
    assert result.asset_activations[0].activation_policy == "SAFE_ABSTENTION"
    diag = planner.diagnostics["assets"][0]
    assert planner.diagnostics["semantic_runtime_available"] is False
    assert diag["semantic_text"] == ""
    assert diag["reason"] == "no_semantic_binding"



def test_semantic_diagnostics_report_eligible_coverage(tmp_path):
    package, transcript, assets, beat = scene_case(tmp_path, 2)
    scorer = Scorer({"concept00": {"concept00": 0.95}, "concept01": {}})
    planner = SemanticActivationPlanner(scorer=scorer)
    planner.enrich(package, transcript, assets, [beat])

    assert planner.diagnostics["eligible_asset_count"] == 2
    assert planner.diagnostics["trusted_eligible_count"] == 1
    assert planner.diagnostics["inherited_eligible_count"] == 0
    assert planner.diagnostics["eligible_coverage"] == pytest.approx(0.5)
    assert planner.diagnostics["semantic_authority"] == "final_package"