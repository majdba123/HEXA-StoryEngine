from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

from app.final_package import FinalPackageLoader
from app.final_package.models import (
    ContinuityPayload,
    ImageSpecPayload,
    RelationPayload,
    ScriptSpanPayload,
    SemanticEventPayload,
    SemanticGroupPayload,
    SemanticProgressionPayload,
    SourceProvenancePayload,
    UnifiedFinalPackagePayload,
    UnifiedObjectPayload,
    UnifiedScenePayload,
    VisualLocatorPayload,
    VisualProgressionPayload,
    VisualStatePayload,
)
from app.pipeline import StoryEnginePipeline
from app.shared.errors import InvalidPackageError
from tests.support.unified_package import write_unified_package


_FIELDS = {
    UnifiedFinalPackagePayload: "contract contract_version package_id project_slug language builder_target timing_authority script_audio_relationship canonical_script image_spec source_provenance scenes",
    ImageSpecPayload: "directory format width height",
    SourceProvenancePayload: "source_contract_version source_package_name source_sha256 conversion_mode",
    UnifiedScenePayload: "scene_id order image title narration_hint script_span purpose visual_concept relation_to_previous character_category objects visual_progression semantic_groups semantic_events relations semantic_progression",
    UnifiedObjectPayload: "unit_id asset_id scene_id object_type source_asset_id semantic_name visual_concept semantic_meaning role semantic_role semantic_intent narrative_function binding_type script_text script_span appear_trigger focus_trigger exit_trigger semantic_group_id sequence_order parent_asset_id children_asset_ids confidence interaction_target relationship semantic_event_id anchor_granularity visual_focus visual_state continuity compound_visual_classification internal_progression_unavailable needs_review ambiguity_reason visual_locator referent_id",
    VisualProgressionPayload: "action event_id order targets trigger",
    SemanticGroupPayload: "semantic_group_id script_text animation_policy asset_ids",
    SemanticEventPayload: "semantic_event_id scene_id script_text script_span anchor_granularity sequence_order visual_leader_asset_id participant_asset_ids context_asset_ids result_asset_ids text_anchor_asset_id confidence needs_review ambiguity_reason depends_on_event_ids",
    RelationPayload: "relation_id subject_asset_id relation_type relationship object_asset_id result_asset_id connector_asset_id script_text script_span confidence",
    SemanticProgressionPayload: "type event_order",
    ScriptSpanPayload: "text global_char_start global_char_end",
    VisualLocatorPayload: "coordinate_space cx cy width height",
    VisualStatePayload: "before after",
    ContinuityPayload: "mode target_asset_id",
}


def test_payload_models_are_field_for_field_locked_to_unified_final_package_2_0() -> None:
    for model, fields in _FIELDS.items():
        assert set(model.model_fields) == set(fields.split()), model.__name__
        assert model.model_config.get("extra") == "forbid", model.__name__


def test_unified_contract_identity_is_literal_locked() -> None:
    schema = UnifiedFinalPackagePayload.model_json_schema()
    assert schema["properties"]["contract"]["const"] == "HEXA_UNIFIED_FINAL_PACKAGE"
    assert schema["properties"]["contract_version"]["const"] == "2.0"


def test_unknown_nested_object_field_fails_closed_at_loader_boundary(tmp_path: Path) -> None:
    source = write_unified_package(
        tmp_path / "source-unknown-field",
        script="alpha",
        scenes=[{
            "scene_id": "SCENE_001",
            "order": 0,
            "script_span": {"text": "alpha", "global_char_start": 0, "global_char_end": 5},
            "assets": [{
                "unit_id": "A",
                "asset_id": "A",
                "script_text": "alpha",
                "script_span": {"text": "alpha", "global_char_start": 0, "global_char_end": 5},
            }],
        }],
    )
    package_json = source / "package.json"
    payload = json.loads(package_json.read_text(encoding="utf-8"))
    payload["scenes"][0]["objects"][0]["future_contract_field"] = "must-be-explicitly-modeled"
    package_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    with pytest.raises(InvalidPackageError, match="future_contract_field"):
        FinalPackageLoader().load(source, tmp_path / "unknown-field-work")


def test_maximal_unified_contract_survives_boundary_without_montage_field_loss(tmp_path: Path) -> None:
    script = "alpha beta"
    span = {"text": script, "global_char_start": 0, "global_char_end": len(script)}
    source = write_unified_package(
        tmp_path / "source",
        script=script,
        package_id="contract-lock-v2",
        scenes=[{
            "scene_id": "SCENE_001", "order": 0, "script_span": span,
            "assets": [
                {"unit_id": "A", "asset_id": "A", "source_asset_id": "source-A",
                 "role": "PRIMARY", "semantic_role": "PRIMARY", "binding_type": "EXPLICIT",
                 "script_text": "alpha", "script_span": {"text": "alpha", "global_char_start": 0, "global_char_end": 5},
                 "semantic_group_id": "G1", "sequence_order": 1, "semantic_event_id": "E1",
                 "visual_locator": {"coordinate_space": "normalized_scene", "cx": 0.25, "cy": 0.5, "width": 0.2, "height": 0.3}},
                {"unit_id": "B", "asset_id": "B", "source_asset_id": "source-B",
                 "role": "SUPPORTING", "semantic_role": "RESULT", "binding_type": "EXPLICIT",
                 "script_text": "beta", "script_span": {"text": "beta", "global_char_start": 6, "global_char_end": 10},
                 "semantic_group_id": "G1", "sequence_order": 2, "parent_asset_id": "A",
                 "semantic_event_id": "E1", "visual_state": {"before": "PENDING", "after": "DONE"},
                 "visual_locator": {"coordinate_space": "normalized_scene", "cx": 0.75, "cy": 0.5, "width": 0.2, "height": 0.3}},
            ],
            "semantic_groups": [{"semantic_group_id": "G1", "script_text": script, "animation_policy": "SEQUENTIAL_WITHIN_PHRASE", "asset_ids": ["A", "B"]}],
            "semantic_events": [{"semantic_event_id": "E1", "script_text": script, "script_span": span, "sequence_order": 1, "visual_leader_asset_id": "A", "participant_asset_ids": [], "context_asset_ids": [], "result_asset_ids": ["B"], "text_anchor_asset_id": "A", "depends_on_event_ids": []}],
            "relations": [{"relation_id": "R1", "subject_asset_id": "A", "relation_type": "ENABLES", "object_asset_id": "B", "result_asset_id": "B", "connector_asset_id": "A", "script_text": script, "script_span": span}],
            "visual_progression": [{"action": "EXPLAIN", "event_id": "E1", "order": 7, "targets": ["A", "B"], "trigger": span}],
            "semantic_progression": {"type": "CAUSE_TO_RESULT", "event_order": ["E1"]},
        }],
    )
    scene = FinalPackageLoader().load(source, tmp_path / "work").scenes[0]
    assert scene.assets[0].source_asset_id == "source-A"
    assert scene.assets[1].parent_asset_id == "A"
    assert scene.relations[0].relation_id == "R1"
    assert scene.relations[0].connector_asset_id == "A"
    assert (scene.visual_progression[0].event_id, scene.visual_progression[0].order) == ("E1", 7)


def test_pipeline_generate_has_unified_package_as_only_script_source() -> None:
    parameters = inspect.signature(StoryEnginePipeline.generate).parameters
    assert {"package_path", "audio_path"} <= set(parameters)
    assert {"script", "canonical_script"}.isdisjoint(parameters)
