from __future__ import annotations

import random
from pathlib import Path

from app.models import PackageModel, SceneSource


def make_package(
    root: Path,
    *,
    seed: int = 1001,
    scene_count: int = 3,
    assets_per_scene: int = 3,
    events_per_scene: int = 2,
    with_relations: bool = True,
    with_locators: bool = True,
    optional_metadata: bool = True,
) -> PackageModel:
    rng = random.Random(seed)
    script_parts: list[str] = []
    scenes: list[SceneSource] = []
    binding_scenes: list[dict] = []
    cursor = 0

    for scene_index in range(scene_count):
        scene_id = f"SCENE_{scene_index + 1:03d}"
        phrase = f"scene{scene_index + 1} alpha beta gamma"
        if script_parts:
            cursor += 1
        start = cursor
        cursor += len(phrase)
        end = cursor
        script_parts.append(phrase)

        units: list[dict] = []
        assets: list[dict] = []
        event_rows: list[dict] = []
        groups: list[dict] = []
        asset_ids: list[str] = []
        for asset_index in range(assets_per_scene):
            asset_id = f"{scene_id}_A{asset_index + 1:02d}"
            asset_ids.append(asset_id)
            event_index = min(asset_index, max(0, events_per_scene - 1))
            event_id = f"{scene_id}_E{event_index + 1:02d}" if events_per_scene else None
            binding_type = rng.choice(["EXPLICIT", "SEMANTIC", "SUPPORT"])
            role = "primary" if asset_index == 0 else "supporting"
            asset = {
                "scene_id": scene_id,
                "asset_id": asset_id,
                "unit_id": asset_id,
                "type": "VISUAL_ASSET_INTENT",
                "role": role,
                "semantic_role": "OBJECT",
                "semantic_meaning": f"meaning {asset_index}",
                "binding_type": binding_type,
                "script_text": phrase,
                "script_span": {
                    "text": phrase,
                    "global_char_start": start,
                    "global_char_end": end,
                },
                "semantic_group_id": f"{scene_id}_G01",
                "sequence_order": asset_index + 1,
                "semantic_event_id": event_id,
                "anchor_granularity": "SCENE_PHRASE",
                "visual_focus": "PRIMARY" if asset_index == 0 else "SUPPORT",
                "compound_visual_classification": "SEPARABLE_SAFE",
                "confidence": 0.95,
            }
            if with_locators:
                asset["visual_locator"] = {
                    "coordinate_space": "normalized_scene",
                    "cx": min(0.9, 0.1 + (asset_index + 1) / (assets_per_scene + 1)),
                    "cy": 0.5,
                    "width": 0.12,
                    "height": 0.18,
                }
            if optional_metadata:
                asset["future_additive_metadata"] = {"seed": seed}
            units.append(dict(asset))
            assets.append(dict(asset))

        if assets_per_scene:
            groups.append({
                "semantic_group_id": f"{scene_id}_G01",
                "script_text": phrase,
                "animation_policy": "SEQUENTIAL_WITHIN_PHRASE",
                "asset_ids": asset_ids,
            })

        for event_index in range(events_per_scene):
            event_id = f"{scene_id}_E{event_index + 1:02d}"
            owned = [
                asset_id for idx, asset_id in enumerate(asset_ids)
                if min(idx, max(0, events_per_scene - 1)) == event_index
            ]
            leader = owned[0] if owned else (asset_ids[0] if asset_ids else None)
            deps = [f"{scene_id}_E{event_index:02d}"] if event_index > 0 else []
            event_rows.append({
                "semantic_event_id": event_id,
                "scene_id": scene_id,
                "script_text": phrase,
                "script_span": {"global_char_start": start, "global_char_end": end},
                "anchor_granularity": "SCENE_PHRASE",
                "sequence_order": event_index + 1,
                "visual_leader_asset_id": leader,
                "participant_asset_ids": owned[1:],
                "context_asset_ids": [],
                "result_asset_ids": owned[-1:] if event_index == events_per_scene - 1 else [],
                "text_anchor_asset_id": leader,
                "depends_on_event_ids": deps,
                "confidence": 0.98,
            })

        relations = []
        if with_relations and len(asset_ids) >= 2:
            relations.append({
                "subject_asset_id": asset_ids[0],
                "relation_type": "CONNECTS_TO",
                "object_asset_id": asset_ids[1],
            })

        scene = SceneSource(
            id=scene_id,
            image_path=root / f"{scene_id}.png",
            order=scene_index,
            narration_hint=phrase,
            script_char_start=start,
            script_char_end=end - 1,
            purpose=f"purpose {scene_index}",
            visual_concept=f"concept {scene_index}",
            units=units,
            semantic_events=event_rows,
            semantic_progression={
                "type": "LINEAR",
                "event_order": [row["semantic_event_id"] for row in event_rows],
            } if event_rows else None,
        )
        scenes.append(scene)
        binding_scenes.append({
            "scene_id": scene_id,
            "script_text": phrase,
            "assets": assets,
            "semantic_groups": groups,
            "semantic_events": event_rows,
            "relations": relations,
            "progression": scene.semantic_progression,
        })

    script = " ".join(script_parts)
    return PackageModel(
        root=root,
        package_id=f"generated-{seed}",
        scenes=scenes,
        script=script,
        manifest={"package_schema": "HEXA_V20_SCENE_PACKAGE", "package_version": "1.2"},
        semantic_bindings={
            "schema_name": "HEXA_ASSET_LEVEL_SEMANTIC_BINDINGS",
            "schema_version": "1.2",
            "scenes": binding_scenes,
        },
    )
