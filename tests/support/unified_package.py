from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping, Sequence

from PIL import Image


def _span(value: Mapping[str, Any] | None, script: str, *, default_text: str | None = None) -> dict[str, Any]:
    value = value or {}
    start = value.get("global_char_start", value.get("char_start"))
    end = value.get("global_char_end", value.get("char_end"))
    text = value.get("text", value.get("phrase", default_text))
    if start is not None and end is not None:
        start_i, end_i = int(start), int(end)
        if text is not None and 0 <= start_i <= end_i < len(script) and script[start_i:end_i] != text and script[start_i:end_i + 1] == text:
            end = end_i + 1
        elif text is None and 0 <= start_i <= end_i <= len(script):
            text = script[start_i:end_i]
    return {
        "text": text,
        "global_char_start": int(start) if start is not None else None,
        "global_char_end": int(end) if end is not None else None,
    }


def _locator(value: Mapping[str, Any] | None) -> dict[str, Any]:
    value = value or {}
    return {
        "coordinate_space": value.get("coordinate_space"),
        "cx": value.get("cx"),
        "cy": value.get("cy"),
        "width": value.get("width"),
        "height": value.get("height"),
    }


def _object(scene_id: str, row: Mapping[str, Any], script: str) -> dict[str, Any]:
    asset_id = str(row.get("asset_id") or row.get("unit_id"))
    script_text = row.get("script_text")
    script_span = _span(row.get("script_span"), script, default_text=script_text)
    appear = _span(row.get("appear_trigger") or row.get("script_span"), script, default_text=script_text)
    focus = _span(row.get("focus_trigger"), script)
    exit_trigger = _span(row.get("exit_trigger"), script)
    visual_state = row.get("visual_state") if isinstance(row.get("visual_state"), Mapping) else {}
    continuity = row.get("continuity") if isinstance(row.get("continuity"), Mapping) else {}
    return {
        "unit_id": str(row.get("unit_id") or asset_id),
        "asset_id": asset_id,
        "scene_id": scene_id,
        "object_type": str(row.get("object_type") or row.get("type") or "VISUAL_ASSET_INTENT"),
        "source_asset_id": row.get("source_asset_id"),
        "semantic_name": row.get("semantic_name"),
        "visual_concept": row.get("visual_concept"),
        "semantic_meaning": row.get("semantic_meaning"),
        "role": row.get("role"),
        "semantic_role": row.get("semantic_role"),
        "semantic_intent": row.get("semantic_intent"),
        "narrative_function": row.get("narrative_function"),
        "binding_type": row.get("binding_type"),
        "script_text": script_text,
        "script_span": script_span,
        "appear_trigger": appear,
        "focus_trigger": focus,
        "exit_trigger": exit_trigger,
        "semantic_group_id": row.get("semantic_group_id"),
        "sequence_order": row.get("sequence_order"),
        "parent_asset_id": row.get("parent_asset_id"),
        "children_asset_ids": list(row.get("children_asset_ids") or []),
        "confidence": float(row.get("confidence", 1.0)),
        "interaction_target": row.get("interaction_target"),
        "relationship": row.get("relationship"),
        "semantic_event_id": row.get("semantic_event_id"),
        "anchor_granularity": row.get("anchor_granularity"),
        "visual_focus": row.get("visual_focus"),
        "visual_state": {"before": visual_state.get("before"), "after": visual_state.get("after")},
        "continuity": {"mode": continuity.get("mode"), "target_asset_id": continuity.get("target_asset_id")},
        "compound_visual_classification": row.get("compound_visual_classification"),
        "internal_progression_unavailable": bool(row.get("internal_progression_unavailable", False)),
        "needs_review": bool(row.get("needs_review", False)),
        "ambiguity_reason": row.get("ambiguity_reason"),
        "visual_locator": _locator(row.get("visual_locator")),
    }


def _event(scene_id: str, row: Mapping[str, Any], script: str) -> dict[str, Any]:
    return {
        "semantic_event_id": str(row["semantic_event_id"]),
        "scene_id": scene_id,
        "script_text": row.get("script_text"),
        "script_span": _span(row.get("script_span"), script, default_text=row.get("script_text")),
        "anchor_granularity": row.get("anchor_granularity"),
        "sequence_order": row.get("sequence_order"),
        "visual_leader_asset_id": row.get("visual_leader_asset_id"),
        "participant_asset_ids": list(row.get("participant_asset_ids") or []),
        "context_asset_ids": list(row.get("context_asset_ids") or []),
        "result_asset_ids": list(row.get("result_asset_ids") or []),
        "text_anchor_asset_id": row.get("text_anchor_asset_id"),
        "confidence": float(row.get("confidence", 1.0)),
        "needs_review": bool(row.get("needs_review", False)),
        "ambiguity_reason": row.get("ambiguity_reason"),
        "depends_on_event_ids": list(row.get("depends_on_event_ids") or []),
    }


def _relation(row: Mapping[str, Any], script: str) -> dict[str, Any]:
    relation_type = row.get("relation_type") or row.get("relationship")
    return {
        "relation_id": row.get("relation_id"),
        "subject_asset_id": str(row["subject_asset_id"]),
        "relation_type": relation_type,
        "relationship": row.get("relationship") or relation_type,
        "object_asset_id": str(row["object_asset_id"]),
        "result_asset_id": row.get("result_asset_id"),
        "connector_asset_id": row.get("connector_asset_id"),
        "script_text": row.get("script_text"),
        "script_span": _span(row.get("script_span"), script, default_text=row.get("script_text")),
        "confidence": float(row.get("confidence", 1.0)),
    }


def write_unified_package(
    root: Path,
    *,
    script: str,
    scenes: Sequence[Mapping[str, Any]],
    package_id: str = "test-unified-package",
    image_size: tuple[int, int] = (320, 180),
    create_images: bool = True,
) -> Path:
    """Write a native Unified Final Package 2.0 fixture.

    `scenes` accepts concise semantic rows used by layer tests; this builder expands
    them into the exact production schema so test packages cannot drift from 2.0.
    """
    package = root
    package.mkdir(parents=True, exist_ok=True)
    images_dir = package / "images"
    images_dir.mkdir(exist_ok=True)
    payload_scenes: list[dict[str, Any]] = []
    for index, source in enumerate(scenes):
        row = deepcopy(dict(source))
        scene_id = str(row["scene_id"])
        image_rel = str(row.get("image") or f"images/{scene_id}.png")
        if create_images:
            image_path = package / image_rel
            image_path.parent.mkdir(parents=True, exist_ok=True)
            if not image_path.exists():
                Image.new("RGB", image_size, "white").save(image_path)
        objects_source = list(row.get("objects") or row.get("assets") or row.get("units") or [])
        objects = [_object(scene_id, item, script) for item in objects_source]
        # Derive children if concise fixtures only author parent ownership.
        children: dict[str, list[str]] = {}
        for item in objects:
            if item["parent_asset_id"]:
                children.setdefault(item["parent_asset_id"], []).append(item["asset_id"])
        for item in objects:
            if not item["children_asset_ids"] and item["asset_id"] in children:
                item["children_asset_ids"] = children[item["asset_id"]]
        groups = []
        for group in row.get("semantic_groups") or []:
            groups.append({
                "semantic_group_id": str(group["semantic_group_id"]),
                "script_text": group.get("script_text"),
                "animation_policy": str(group.get("animation_policy") or "SEQUENTIAL_WITHIN_PHRASE"),
                "asset_ids": list(group.get("asset_ids") or []),
            })
        events = [_event(scene_id, item, script) for item in (row.get("semantic_events") or [])]
        relations = [_relation(item, script) for item in (row.get("relations") or [])]
        progression_source = row.get("semantic_progression") or row.get("progression") or {}
        visual_progression = []
        for progression in row.get("visual_progression") or []:
            visual_progression.append({
                "action": str(progression.get("action") or "EXPLAIN"),
                "event_id": progression.get("event_id"),
                "order": progression.get("order"),
                "targets": list(progression.get("targets") or []),
                "trigger": _span(progression.get("trigger"), script),
            })
        scene_span = _span(row.get("script_span"), script)
        if scene_span["global_char_start"] is None:
            scene_span = {"text": script, "global_char_start": 0, "global_char_end": len(script)}
        payload_scenes.append({
            "scene_id": scene_id,
            "order": int(row.get("order", index)),
            "image": image_rel,
            "title": row.get("title"),
            "narration_hint": row.get("narration_hint"),
            "script_span": scene_span,
            "purpose": row.get("purpose"),
            "visual_concept": row.get("visual_concept"),
            "relation_to_previous": row.get("relation_to_previous"),
            "character_category": row.get("character_category"),
            "objects": objects,
            "visual_progression": visual_progression,
            "semantic_groups": groups,
            "semantic_events": events,
            "relations": relations,
            "semantic_progression": {
                "type": progression_source.get("type"),
                "event_order": list(progression_source.get("event_order") or []),
            },
        })
    payload = {
        "contract": "HEXA_UNIFIED_FINAL_PACKAGE",
        "contract_version": "2.0",
        "package_id": package_id,
        "project_slug": package_id,
        "language": "ar" if any("\u0600" <= ch <= "\u06ff" for ch in script) else "en",
        "builder_target": "HEXA_VIDEO_BUILDER_V20",
        "timing_authority": "FINAL_VOICE_OVER_SEPARATE_INPUT",
        "script_audio_relationship": "EXACT_MATCH",
        "canonical_script": script,
        "image_spec": {"directory": "images", "format": "png", "width": image_size[0], "height": image_size[1]},
        "source_provenance": {
            "source_contract_version": "2.0",
            "source_package_name": package_id,
            "source_sha256": "0" * 64,
            "conversion_mode": "NATIVE_TEST_FIXTURE",
        },
        "scenes": payload_scenes,
    }
    (package / "package.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return package
