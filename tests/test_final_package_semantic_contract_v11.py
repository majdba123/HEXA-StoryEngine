from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.input.loader import FinalPackageLoader
from app.models import (
    PackageModel,
    SceneSource,
    StoryBeat,
    Transcript,
    TranscriptWord,
    VisualAsset,
)
from app.shared.errors import InvalidPackageError
from app.story.activation import SemanticActivationPlanner
from app.story.semantic import PackageStoryInterpreter
from app.story.binding import SemanticAssetBinder


def _write_package(
    tmp_path: Path,
    *,
    script: str,
    semantic_scene: dict,
) -> Path:
    package = tmp_path / "package"
    scenes = package / "scenes"
    scenes.mkdir(parents=True)
    (scenes / "SCENE_001.png").write_bytes(b"png")
    (package / "canonical_script.txt").write_text(script, encoding="utf-8")
    unit_rows = [
        {
            "unit_id": asset["asset_id"],
            "asset_id": asset["asset_id"],
            "type": "VISUAL_ASSET_INTENT",
            "role": asset.get("semantic_role", "OBJECT"),
        }
        for asset in semantic_scene["assets"]
    ]
    (package / "scene_plan.json").write_text(
        json.dumps(
            {
                "scenes": [
                    {
                        "scene_id": "SCENE_001",
                        "order": 1,
                        "image": "scenes/SCENE_001.png",
                        "script_span": {
                            "global_char_start": 0,
                            "global_char_end": len(script) - 1,
                            "text": script,
                        },
                        "units": unit_rows,
                        "visual_progression": [
                            {
                                "event_id": "E1",
                                "order": 1,
                                "action": "EXPLAIN",
                                "targets": [],
                                "trigger": {
                                    "phrase": script,
                                    "global_char_start": 0,
                                    "global_char_end": len(script) - 1,
                                },
                            }
                        ],
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (package / "semantic_bindings.json").write_text(
        json.dumps(
            {
                "schema_name": "HEXA_ASSET_LEVEL_SEMANTIC_BINDINGS",
                "asset_is_semantic_intent_not_cutout": True,
                "no_fixed_timing": True,
                "cutout_mapping_cardinality": "ZERO_OR_ONE_OR_MANY",
                "scenes": [semantic_scene],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return package


def test_group_phrase_may_be_wider_than_precise_asset_trigger(tmp_path: Path) -> None:
    script = "برنامج قديم ما تم تحديثه من سنوات"
    semantic_scene = {
        "scene_id": "SCENE_001",
        "semantic_groups": [
            {
                "semantic_group_id": "g",
                "script_text": script,
                "animation_policy": "SEQUENTIAL_WITHIN_PHRASE",
                "asset_ids": ["program", "warning", "years"],
            }
        ],
        "assets": [
            {
                "asset_id": "program",
                "script_text": "برنامج قديم",
                "script_span": {"char_start": 0, "char_end": 11},
                "binding_type": "EXPLICIT",
                "semantic_group_id": "g",
                "sequence_order": 1,
                "confidence": 1.0,
            },
            {
                "asset_id": "warning",
                "script_text": "ما تم تحديثه",
                "script_span": {"char_start": 12, "char_end": 24},
                "binding_type": "EXPLICIT",
                "semantic_group_id": "g",
                "sequence_order": 2,
                "confidence": 1.0,
                "visual_focus": "PRIMARY",
                "visual_state": {"before": "NORMAL", "after": "WARNING"},
            },
            {
                "asset_id": "years",
                "script_text": "من سنوات",
                "script_span": {"char_start": 25, "char_end": 33},
                "binding_type": "SEMANTIC",
                "semantic_group_id": "g",
                "sequence_order": 3,
                "confidence": 0.95,
            },
        ],
        "relations": [
            {
                "relation_id": "rel-1",
                "subject_asset_id": "program",
                "relationship": "RESULTS_IN",
                "object_asset_id": "warning",
                "result_asset_id": "years",
                "script_text": "ما تم تحديثه من سنوات",
                "script_span": {"char_start": 12, "char_end": 33},
                "confidence": 0.98,
            }
        ],
    }

    loaded = FinalPackageLoader().load(
        _write_package(tmp_path, script=script, semantic_scene=semantic_scene),
        tmp_path / "work",
    )

    assets = loaded.semantic_bindings["scenes"][0]["assets"]
    assert [row["script_text"] for row in assets] == [
        "برنامج قديم",
        "ما تم تحديثه",
        "من سنوات",
    ]


def test_precise_script_span_must_match_exact_half_open_text(tmp_path: Path) -> None:
    script = "alpha beta"
    semantic_scene = {
        "scene_id": "SCENE_001",
        "semantic_groups": [{
            "semantic_group_id": "g",
            "script_text": script,
            "asset_ids": ["a"],
        }],
        "assets": [{
            "asset_id": "a",
            "script_text": "alpha",
            "script_span": {"char_start": 1, "char_end": 6},
            "binding_type": "EXPLICIT",
            "semantic_group_id": "g",
            "sequence_order": 1,
            "confidence": 1.0,
        }],
    }

    with pytest.raises(InvalidPackageError, match="script_span does not match"):
        FinalPackageLoader().load(
            _write_package(tmp_path, script=script, semantic_scene=semantic_scene),
            tmp_path / "work",
        )


def test_final_package_relations_focus_and_state_enter_story_context() -> None:
    scene = SceneSource(
        id="SCENE_001",
        image_path=Path("/scene.png"),
        order=0,
        units=[
            {"unit_id": "actor", "type": "VISUAL_ASSET_INTENT", "role": "CHARACTER"},
            {"unit_id": "target", "type": "VISUAL_ASSET_INTENT", "role": "PRIMARY"},
            {"unit_id": "result", "type": "VISUAL_ASSET_INTENT", "role": "RESULT"},
        ],
    )
    semantic_scene = {
        "assets": [
            {"asset_id": "actor", "semantic_meaning": "actor"},
            {"asset_id": "target", "semantic_meaning": "target", "visual_focus": "PRIMARY"},
            {
                "asset_id": "result",
                "semantic_meaning": "result",
                "visual_state": {"before": "SAFE", "after": "CHANGED"},
            },
        ],
        "relations": [{
            "subject_asset_id": "actor",
            "relationship": "CREATES",
            "object_asset_id": "target",
            "result_asset_id": "result",
            "script_text": "creates result",
            "script_span": {"char_start": 2, "char_end": 16},
            "confidence": 0.97,
        }],
    }

    context = PackageStoryInterpreter().interpret(
        scene,
        {"action": "EXPLAIN", "targets": []},
        is_first_beat=False,
        semantic_binding_scene=semantic_scene,
    )

    authored = next(row for row in context.relations if row.authority == "FINAL_PACKAGE_ASSET_RELATION")
    assert authored.source_unit_id == "actor"
    assert authored.target_unit_id == "target"
    assert authored.result_unit_id == "result"
    assert context.focus_unit_ids == ["target"]
    assert context.visual_states["result"] == {"before": "SAFE", "after": "CHANGED"}


def test_story_binder_prefers_locator_proven_activation_and_authored_focus(tmp_path: Path) -> None:
    scene = SceneSource(
        id="SCENE_001",
        image_path=tmp_path / "scene.png",
        order=0,
        units=[
            {"unit_id": "concept-a", "type": "VISUAL_ASSET_INTENT"},
            {"unit_id": "concept-b", "type": "VISUAL_ASSET_INTENT"},
        ],
    )
    assets = [
        VisualAsset(
            id="large",
            scene_id=scene.id,
            role="primary",
            image_path=tmp_path / "large.png",
            extraction_method="test",
            source_area_ratio=0.40,
        ),
        VisualAsset(
            id="small",
            scene_id=scene.id,
            role="support",
            image_path=tmp_path / "small.png",
            extraction_method="test",
            source_area_ratio=0.08,
        ),
    ]
    from app.models import AssetActivation

    beat = StoryBeat(
        id="beat-1",
        scene_id=scene.id,
        start=0.0,
        end=2.0,
        narration="x",
        primary_asset_ids=["large"],
        support_asset_ids=["small"],
        action="INTRODUCE",
        asset_activations=[
            AssetActivation(
                asset_id="large",
                semantic_unit_id="concept-a",
                source="final_package_semantic_binding",
                policy="EXPLICIT",
                confidence=1.0,
            ),
            AssetActivation(
                asset_id="small",
                semantic_unit_id="concept-b",
                source="final_package_semantic_binding",
                policy="EXPLICIT",
                confidence=1.0,
                visual_focus="PRIMARY",
            ),
        ],
    )

    binding = SemanticAssetBinder().bind(
        scene=scene,
        assets=assets,
        action="REVEAL",
        beat=beat,
    )

    assert dict(binding.semantic_asset_map) == {
        "concept-a": "large",
        "concept-b": "small",
    }
    assert binding.focus_asset_id == "small"


def test_activation_uses_authored_span_when_phrase_repeats(tmp_path: Path) -> None:
    script = "alpha beta alpha"
    scene = SceneSource(
        id="scene-1",
        image_path=tmp_path / "scene.png",
        order=0,
        script_char_start=0,
        script_char_end=len(script) - 1,
        units=[{"unit_id": "intent", "type": "VISUAL_ASSET_INTENT"}],
    )
    package = PackageModel(
        root=tmp_path,
        package_id="p",
        scenes=[scene],
        script=script,
        semantic_bindings={
            "schema_name": "HEXA_ASSET_LEVEL_SEMANTIC_BINDINGS",
            "scenes": [{
                "scene_id": "scene-1",
                "semantic_groups": [{
                    "semantic_group_id": "g",
                    "script_text": script,
                    "animation_policy": "SEQUENTIAL_WITHIN_PHRASE",
                    "asset_ids": ["intent"],
                }],
                "assets": [{
                    "asset_id": "intent",
                    "script_text": "alpha",
                    "script_span": {"char_start": 11, "char_end": 16},
                    "binding_type": "EXPLICIT",
                    "semantic_group_id": "g",
                    "sequence_order": 1,
                    "confidence": 1.0,
                }],
            }],
        },
    )
    asset = VisualAsset(
        id="intent",
        scene_id="scene-1",
        role="primary",
        image_path=tmp_path / "a.png",
        extraction_method="test",
        source_area_ratio=0.2,
    )
    transcript = Transcript(
        duration=2.0,
        segments=[],
        words=[
            TranscriptWord(start=0.1, end=0.3, text="alpha", char_start=0, char_end=5),
            TranscriptWord(start=0.5, end=0.7, text="beta", char_start=6, char_end=10),
            TranscriptWord(start=1.1, end=1.3, text="alpha", char_start=11, char_end=16),
        ],
    )
    beat = StoryBeat(
        id="beat-1",
        scene_id="scene-1",
        start=0.0,
        end=2.0,
        audio_start=0.0,
        audio_end=2.0,
        narration=script,
        primary_asset_ids=["intent"],
        action="INTRODUCE",
    )

    planned = SemanticActivationPlanner().enrich(
        package, transcript, [asset], [beat]
    )[0]

    activation = planned.asset_activations[0]
    assert activation.trigger_char_start == 11
    assert activation.trigger_char_end == 16
    assert activation.spoken_start == pytest.approx(1.1)
    assert "exact_final_package_script_span" in activation.evidence
