from __future__ import annotations

from dataclasses import dataclass
import json
import random
from pathlib import Path

from PIL import Image

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



# Disk-backed factory used to certify the actual Final Package boundary. The legacy
# make_package() fixture above remains for representation-only Canonical tests.


@dataclass(frozen=True, slots=True)
class DiskPackageShape:
    scenes: int = 1
    assets_per_scene: int = 3
    relations: bool = True
    dependencies: bool = True
    locators: str = "none"  # none | partial | all
    extra_metadata: bool = False
    compound: bool = False


def _disk_span(script: str, text: str, start_at: int = 0) -> dict[str, int]:
    start = script.index(text, start_at)
    return {"global_char_start": start, "global_char_end": start + len(text)}


def write_valid_package(root: Path, shape: DiskPackageShape) -> Path:
    package = root / "package"
    scenes_dir = package / "scenes"
    scenes_dir.mkdir(parents=True)

    scene_phrases: list[str] = []
    scene_tokens: list[list[str]] = []
    for scene_index in range(1, shape.scenes + 1):
        tokens = [
            f"s{scene_index}a{asset_index}"
            for asset_index in range(1, shape.assets_per_scene + 1)
        ]
        scene_tokens.append(tokens)
        scene_phrases.append(" ".join(tokens))
    script = " ".join(scene_phrases)
    (package / "canonical_script.txt").write_text(script, encoding="utf-8")

    scene_plan_rows: list[dict] = []
    semantic_scene_rows: list[dict] = []
    top_events: list[dict] = []
    cursor = 0
    for scene_index, (tokens, phrase) in enumerate(
        zip(scene_tokens, scene_phrases), start=1
    ):
        scene_id = f"SCENE_{scene_index:03d}"
        image_rel = f"scenes/{scene_id}.png"
        Image.new("RGB", (64, 64), "white").save(package / image_rel)
        scene_start = script.index(phrase, cursor)
        scene_end = scene_start + len(phrase)
        cursor = scene_end

        assets: list[dict] = []
        events: list[dict] = []
        relations: list[dict] = []
        group_id = f"{scene_id}_G01"
        for asset_index, token in enumerate(tokens, start=1):
            asset_id = f"{scene_id}_A{asset_index:02d}"
            event_id = f"{scene_id}_E{asset_index:02d}"
            span = _disk_span(script, token, scene_start)
            asset = {
                "scene_id": scene_id,
                "asset_id": asset_id,
                "script_text": token,
                "script_span": span,
                "anchor_granularity": "EXACT_WORD",
                "binding_type": "EXPLICIT" if asset_index % 2 else "SEMANTIC",
                "semantic_group_id": group_id,
                "sequence_order": asset_index,
                "confidence": 0.99,
                "semantic_role": (
                    "RESULT"
                    if asset_index == len(tokens)
                    else ("OBJECT" if asset_index > 1 else "SUBJECT")
                ),
                "visual_focus": (
                    "RESULT"
                    if asset_index == len(tokens)
                    else ("PRIMARY" if asset_index == 1 else "SUPPORT")
                ),
                "semantic_event_id": event_id,
                "compound_visual_classification": (
                    "COMPOUND_REQUIRED"
                    if shape.compound and asset_index == len(tokens)
                    else "SEPARABLE_SAFE"
                ),
                "internal_progression_unavailable": bool(
                    shape.compound and asset_index == len(tokens)
                ),
            }
            if shape.locators == "all" or (
                shape.locators == "partial" and asset_index % 2
            ):
                width = min(0.18, 0.8 / max(1, len(tokens)))
                cx = (
                    0.1 + (asset_index - 1) * (0.8 / max(1, len(tokens) - 1))
                    if len(tokens) > 1
                    else 0.5
                )
                asset["visual_locator"] = {
                    "coordinate_space": "normalized_scene",
                    "cx": min(0.9, max(0.1, cx)),
                    "cy": 0.5,
                    "width": width,
                    "height": 0.18,
                }
            if shape.extra_metadata:
                asset["future_additive_metadata"] = {
                    "seed": scene_index * 100 + asset_index
                }
            assets.append(asset)

            event = {
                "semantic_event_id": event_id,
                "scene_id": scene_id,
                "script_text": token,
                "script_span": span,
                "anchor_granularity": "EXACT_WORD",
                "sequence_order": asset_index,
                "visual_leader_asset_id": asset_id,
                "participant_asset_ids": [],
                "context_asset_ids": [],
                "result_asset_ids": [asset_id] if asset_index == len(tokens) else [],
                "text_anchor_asset_id": asset_id,
                "confidence": 0.99,
                "depends_on_event_ids": (
                    [f"{scene_id}_E{asset_index - 1:02d}"]
                    if shape.dependencies and asset_index > 1
                    else []
                ),
            }
            events.append(event)
            top_events.append(event)

            if shape.relations and asset_index > 1:
                relations.append({
                    "relation_id": f"{scene_id}_R{asset_index - 1:02d}",
                    "subject_asset_id": f"{scene_id}_A{asset_index - 1:02d}",
                    "relation_type": "ENABLES",
                    "object_asset_id": asset_id,
                    "script_text": f"{tokens[asset_index - 2]} {token}",
                    "script_span": {
                        "global_char_start": _disk_span(
                            script, tokens[asset_index - 2], scene_start
                        )["global_char_start"],
                        "global_char_end": span["global_char_end"],
                    },
                    "confidence": 0.97,
                })

        group = {
            "semantic_group_id": group_id,
            "script_text": phrase,
            "animation_policy": "SEQUENTIAL_WITHIN_PHRASE",
            "asset_ids": [row["asset_id"] for row in assets],
        }
        progression = {
            "type": "GENERIC_PROGRESS",
            "event_order": [row["semantic_event_id"] for row in events],
        }
        scene_plan_rows.append({
            "scene_id": scene_id,
            "order": scene_index,
            "image": image_rel,
            "script_span": {
                "global_char_start": scene_start,
                "global_char_end": scene_end,
                "text": phrase,
            },
            "purpose": "EXPLAIN",
            "units": [
                {
                    "unit_id": row["asset_id"],
                    "asset_id": row["asset_id"],
                    "type": "VISUAL_ASSET_INTENT",
                    "role": row["semantic_role"],
                    **(
                        {"visual_locator": row["visual_locator"]}
                        if "visual_locator" in row
                        else {}
                    ),
                }
                for row in assets
            ],
            "semantic_events": events,
            "relations": relations,
            "progression": progression,
        })
        semantic_scene_rows.append({
            "scene_id": scene_id,
            "script_text": phrase,
            "assets": assets,
            "semantic_groups": [group],
            "semantic_events": events,
            "relations": relations,
            "progression": progression,
        })

    (package / "manifest.json").write_text(json.dumps({
        "project_id": "test1-generated",
        "package_schema": "HEXA_V20_SCENE_PACKAGE",
        "package_version": "1.2",
        "scene_plan": "scene_plan.json",
        "canonical_script": "canonical_script.txt",
        "semantic_bindings": "semantic_bindings.json",
    }), encoding="utf-8")
    (package / "scene_plan.json").write_text(json.dumps({
        "project_id": "test1-generated",
        "scenes": scene_plan_rows,
    }), encoding="utf-8")
    (package / "semantic_bindings.json").write_text(json.dumps({
        "schema_name": "HEXA_ASSET_LEVEL_SEMANTIC_BINDINGS",
        "schema_version": "1.2",
        "asset_is_semantic_intent_not_cutout": True,
        "cutout_mapping_cardinality": "ZERO_OR_ONE_OR_MANY",
        "no_fixed_timing": True,
        "scenes": semantic_scene_rows,
        "semantic_events": top_events,
    }), encoding="utf-8")
    return package


def seeded_disk_shape(seed: int) -> DiskPackageShape:
    rng = random.Random(seed)
    return DiskPackageShape(
        scenes=rng.randint(1, 5),
        assets_per_scene=rng.randint(1, 8),
        relations=rng.choice([True, False]),
        dependencies=rng.choice([True, False]),
        locators=rng.choice(["none", "partial", "all"]),
        extra_metadata=rng.choice([True, False]),
        compound=rng.choice([True, False]),
    )
