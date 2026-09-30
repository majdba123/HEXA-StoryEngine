"""Mutation matrix: every structural rule of Unified Final Package 2.0 fails closed.

A single valid base package is mutated one rule at a time. Each mutation must be
rejected by the strict loader with a specific message; the unmutated base (including
``relations=[]`` on a scene, as in real packages) must load.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

import pytest

from app.final_package import FinalPackageLoader
from app.shared.errors import InvalidPackageError
from tests.support.unified_package import write_unified_package

SCRIPT = "alpha beta gamma delta"


def _base(root: Path) -> Path:
    return write_unified_package(
        root,
        script=SCRIPT,
        package_id="mutation-base",
        scenes=[
            {
                "scene_id": "SCENE_001",
                "script_span": {"global_char_start": 0, "global_char_end": 10, "text": "alpha beta"},
                "objects": [
                    {"asset_id": "SCENE_001_A", "role": "primary", "binding_type": "EXPLICIT",
                     "script_text": "alpha", "script_span": {"global_char_start": 0, "global_char_end": 5},
                     "semantic_group_id": "SCENE_001_G", "semantic_event_id": "SCENE_001_E1",
                     "visual_locator": {"coordinate_space": "normalized_scene", "cx": 0.3,
                                        "cy": 0.5, "width": 0.3, "height": 0.4}},
                    {"asset_id": "SCENE_001_B", "role": "supporting", "binding_type": "SEMANTIC",
                     "script_text": "beta", "script_span": {"global_char_start": 6, "global_char_end": 10},
                     "semantic_group_id": "SCENE_001_G", "semantic_event_id": "SCENE_001_E1"},
                ],
                "semantic_groups": [
                    {"semantic_group_id": "SCENE_001_G", "asset_ids": ["SCENE_001_A", "SCENE_001_B"]},
                ],
                "semantic_events": [
                    {"semantic_event_id": "SCENE_001_E1", "script_text": "alpha beta",
                     "script_span": {"global_char_start": 0, "global_char_end": 10},
                     "sequence_order": 1, "visual_leader_asset_id": "SCENE_001_A",
                     "text_anchor_asset_id": "SCENE_001_A",
                     "participant_asset_ids": ["SCENE_001_B"]},
                ],
                "relations": [
                    {"subject_asset_id": "SCENE_001_A", "relation_type": "USES",
                     "object_asset_id": "SCENE_001_B"},
                ],
                "visual_progression": [
                    {"action": "EXPLAIN", "targets": ["SCENE_001_A"],
                     "trigger": {"global_char_start": 0, "global_char_end": 5}},
                ],
            },
            {
                "scene_id": "SCENE_002",
                "script_span": {"global_char_start": 11, "global_char_end": 22, "text": "gamma delta"},
                "objects": [
                    {"asset_id": "SCENE_002_C", "role": "primary", "binding_type": "EXPLICIT",
                     "script_text": "gamma", "script_span": {"global_char_start": 11, "global_char_end": 16},
                     "semantic_group_id": "SCENE_002_G", "semantic_event_id": "SCENE_002_E1"},
                    {"asset_id": "SCENE_002_D", "role": "supporting", "binding_type": "SEMANTIC",
                     "script_text": "delta", "script_span": {"global_char_start": 17, "global_char_end": 22},
                     "semantic_group_id": "SCENE_002_G", "semantic_event_id": "SCENE_002_E1"},
                ],
                "semantic_groups": [
                    {"semantic_group_id": "SCENE_002_G", "asset_ids": ["SCENE_002_C", "SCENE_002_D"]},
                ],
                "semantic_events": [
                    {"semantic_event_id": "SCENE_002_E1", "script_text": "gamma delta",
                     "script_span": {"global_char_start": 11, "global_char_end": 22},
                     "sequence_order": 1, "visual_leader_asset_id": "SCENE_002_C",
                     "text_anchor_asset_id": "SCENE_002_C",
                     "result_asset_ids": ["SCENE_002_D"]},
                ],
                "relations": [],
            },
        ],
    )


def _scene(payload: dict, index: int = 0) -> dict:
    return payload["scenes"][index]


def _object(payload: dict, asset_id: str) -> dict:
    return next(
        row for scene in payload["scenes"] for row in scene["objects"] if row["asset_id"] == asset_id
    )


def _event(payload: dict, index: int = 0) -> dict:
    return _scene(payload, index)["semantic_events"][0]


Mutation = Callable[[dict, Path], None]

MUTATIONS: dict[str, tuple[Mutation, str]] = {
    "wrong-contract-version": (lambda p, r: p.update(contract_version="1.2"), "Unified Final Package"),
    "unknown-top-level-field": (lambda p, r: p.update(manifest={}), "invalid Unified Final Package 2.0"),
    "missing-required-field": (lambda p, r: p.pop("scenes"), "invalid Unified Final Package 2.0"),
    "missing-object-field": (lambda p, r: _object(p, "SCENE_001_B").pop("visual_locator"),
                             "invalid Unified Final Package 2.0"),
    "empty-script": (lambda p, r: p.update(canonical_script=""), "canonical_script"),
    "no-scenes": (lambda p, r: p.update(scenes=[]), "no scenes"),
    "empty-object-id": (lambda p, r: _object(p, "SCENE_002_D").update(asset_id="", unit_id=""),
                        "identity is required"),
    "duplicate-scene-id": (lambda p, r: _scene(p, 1).update(scene_id="SCENE_001"), "duplicate scene_id"),
    "duplicate-object-id": (lambda p, r: _object(p, "SCENE_002_D").update(asset_id="SCENE_001_A"),
                            "duplicate"),
    "duplicate-event-id": (lambda p, r: _event(p, 1).update(semantic_event_id="SCENE_001_E1"),
                           "semantic event"),
    "object-scene-mismatch": (lambda p, r: _object(p, "SCENE_001_B").update(scene_id="SCENE_002"),
                              "object scene_id mismatch"),
    "dangling-event-leader": (lambda p, r: _event(p).update(visual_leader_asset_id="GHOST"),
                              "reference is missing"),
    "dangling-event-participant": (lambda p, r: _event(p)["participant_asset_ids"].append("GHOST"),
                                   "reference is missing"),
    "dangling-event-result": (lambda p, r: _event(p, 1)["result_asset_ids"].append("GHOST"),
                              "reference is missing"),
    "dangling-event-dependency": (lambda p, r: _event(p).update(depends_on_event_ids=["GHOST"]),
                                  "reference is missing"),
    "dangling-progression-target": (lambda p, r: _scene(p)["visual_progression"][0]["targets"].append("GHOST"),
                                    "reference is missing"),
    "dangling-relation-object": (lambda p, r: _scene(p)["relations"][0].update(object_asset_id="GHOST"),
                                 "reference is missing"),
    "dangling-group-member": (lambda p, r: _scene(p)["semantic_groups"][0]["asset_ids"].append("GHOST"),
                              "reference is missing"),
    "event-ownership-mismatch": (lambda p, r: _object(p, "SCENE_002_D").update(semantic_event_id=None),
                                 "semantic event ownership mismatch"),
    "reversed-script-span": (lambda p, r: _object(p, "SCENE_001_A")["script_span"].update(
        global_char_start=5, global_char_end=0), "script span"),
    "span-beyond-script": (lambda p, r: _event(p, 1)["script_span"].update(global_char_end=999),
                           "script span"),
    "span-text-mismatch": (lambda p, r: _object(p, "SCENE_001_A")["script_span"].update(text="omega"),
                           "script span text mismatch"),
    "locator-outside-scene": (lambda p, r: _object(p, "SCENE_001_A")["visual_locator"].update(cx=1.4),
                              "visual_locator"),
    "missing-scene-image": (lambda p, r: (r / "images" / "SCENE_002.png").unlink(), "missing scene image"),
    "image-outside-images-dir": (lambda p, r: _scene(p, 1).update(image="SCENE_002.png"), "image"),
}


def _write(root: Path, payload: dict) -> None:
    (root / "package.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8",
    )


def test_unmutated_base_with_empty_relations_loads(tmp_path: Path) -> None:
    root = _base(tmp_path / "package")
    package = FinalPackageLoader().load(root, tmp_path / "work")
    assert package.contract_version == "2.0"
    assert package.scenes[1].relations == ()
    assert package.scenes[0].semantic_carrier_roles


@pytest.mark.parametrize("name", sorted(MUTATIONS))
def test_structural_mutation_fails_closed(tmp_path: Path, name: str) -> None:
    root = _base(tmp_path / "package")
    payload = json.loads((root / "package.json").read_text(encoding="utf-8"))
    mutate, message = MUTATIONS[name]
    mutate(payload, root)
    _write(root, payload)
    with pytest.raises(InvalidPackageError) as caught:
        FinalPackageLoader().load(root, tmp_path / "work")
    assert message in str(caught.value), (name, str(caught.value))


@pytest.mark.parametrize("legacy", ["manifest.json", "scene_plan.json", "semantic_bindings.json"])
def test_final_package_1x_companion_files_stay_unsupported(tmp_path: Path, legacy: str) -> None:
    root = _base(tmp_path / "package")
    (root / legacy).write_text("{}", encoding="utf-8")
    with pytest.raises(InvalidPackageError):
        FinalPackageLoader().load(root, tmp_path / "work")
