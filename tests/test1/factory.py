from __future__ import annotations

from app.canonical import CanonicalPackage
from tests.support.canonical_package import canonical_package
from dataclasses import dataclass
import json
import random
from pathlib import Path

from PIL import Image

from app.models import SceneSource, Transcript, VisualAsset


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
) -> CanonicalPackage:
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
            script_char_end=end,
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
    return canonical_package(
        root=root,
        package_id=f"generated-{seed}",
        scenes=scenes,
        script=script,
        semantics={"scenes": binding_scenes},
    )



# Disk-backed factory used to certify the Unified Final Package 2.0 boundary.


@dataclass(frozen=True, slots=True)
class DiskPackageShape:
    scenes: int = 1
    assets_per_scene: int = 3
    relations: bool = True
    dependencies: bool = True
    dependency_mode: str = "linear"  # none | linear | branching
    locators: str = "none"  # none | partial | all
    extra_metadata: bool = False
    compound: bool = False
    progression: bool = True
    group_count: int = 1
    group_policy: str = "SEQUENTIAL_WITHIN_PHRASE"
    binding_types: tuple[str, ...] = ("EXPLICIT", "SEMANTIC")
    continuity: str = "none"  # none | persist | transform
    reuse_first_asset: bool = False
    script_style: str = "ascii"  # ascii | arabic | numbers
    namespace: str = ""


def _disk_span(script: str, text: str, start_at: int = 0) -> dict[str, int]:
    start = script.index(text, start_at)
    return {"global_char_start": start, "global_char_end": start + len(text)}


def write_valid_package(root: Path, shape: DiskPackageShape) -> Path:
    package = root / "package"
    images_dir = package / "images"
    images_dir.mkdir(parents=True)

    scene_tokens: list[list[str]] = []
    scene_phrases: list[str] = []
    for scene_index in range(1, shape.scenes + 1):
        if shape.script_style == "arabic":
            tokens = [f"مشهد{scene_index}عنصر{i}" for i in range(1, shape.assets_per_scene + 1)]
        elif shape.script_style == "numbers":
            tokens = [
                f"رقم{scene_index}{i}x{scene_index * i * 100}"
                for i in range(1, shape.assets_per_scene + 1)
            ]
        else:
            prefix = shape.namespace.lower() or "s"
            tokens = [f"{prefix}{scene_index}a{i}" for i in range(1, shape.assets_per_scene + 1)]
        scene_tokens.append(tokens)
        scene_phrases.append(" ".join(tokens))
    script = " ".join(scene_phrases)

    scene_rows: list[dict] = []
    cursor = 0
    for scene_index, (tokens, phrase) in enumerate(zip(scene_tokens, scene_phrases), start=1):
        scene_prefix = f"{shape.namespace}_" if shape.namespace else ""
        scene_id = f"{scene_prefix}SCENE_{scene_index:03d}"
        image_rel = f"images/{scene_id}.png"
        Image.new("RGB", (64, 64), "white").save(package / image_rel)
        scene_start = script.index(phrase, cursor)
        scene_end = scene_start + len(phrase)
        cursor = scene_end

        objects: list[dict] = []
        events: list[dict] = []
        relations: list[dict] = []
        group_count = max(1, min(shape.group_count, max(1, len(tokens))))

        parent_children: dict[str, list[str]] = {}
        parent_by_asset: dict[str, str | None] = {}
        for asset_index, _token in enumerate(tokens, start=1):
            asset_id = f"{scene_id}_A{asset_index:02d}"
            parent = None
            binding_type = shape.binding_types[(asset_index - 1) % len(shape.binding_types)]
            if binding_type == "PARENT" and asset_index > 1:
                parent = f"{scene_id}_A01"
                parent_children.setdefault(parent, []).append(asset_id)
            elif binding_type == "PARENT":
                binding_type = "EXPLICIT"
            parent_by_asset[asset_id] = parent

        for asset_index, token in enumerate(tokens, start=1):
            asset_id = f"{scene_id}_A{asset_index:02d}"
            event_id = f"{scene_id}_E{asset_index:02d}"
            group_index = ((asset_index - 1) % group_count) + 1
            group_id = f"{scene_id}_G{group_index:02d}"
            span = _disk_span(script, token, scene_start)
            locator = {"coordinate_space": None, "cx": None, "cy": None, "width": None, "height": None}
            if shape.locators == "all" or (shape.locators == "partial" and asset_index % 2):
                width = min(0.18, 0.8 / max(1, len(tokens)))
                cx = 0.5 if len(tokens) == 1 else 0.1 + (asset_index - 1) * (0.8 / (len(tokens) - 1))
                locator = {
                    "coordinate_space": "normalized_scene",
                    "cx": min(0.9, max(0.1, cx)),
                    "cy": 0.5,
                    "width": width,
                    "height": 0.18,
                }
            continuity = {"mode": None, "target_asset_id": None}
            if shape.continuity == "persist" and asset_index == 1:
                continuity = {"mode": "PERSIST", "target_asset_id": None}
            elif shape.continuity == "transform" and asset_index == 1 and len(tokens) > 1:
                continuity = {"mode": "TRANSFORM_TO", "target_asset_id": f"{scene_id}_A02"}
            binding_type = shape.binding_types[(asset_index - 1) % len(shape.binding_types)]
            if binding_type == "PARENT" and asset_index == 1:
                binding_type = "EXPLICIT"
            obj = {
                "unit_id": asset_id,
                "asset_id": asset_id,
                "scene_id": scene_id,
                "object_type": "VISUAL_ASSET_INTENT",
                "source_asset_id": None,
                "semantic_name": f"object_{asset_index}",
                "visual_concept": f"visual {token}",
                "semantic_meaning": token,
                "role": "primary" if asset_index == 1 else "supporting",
                "semantic_role": "RESULT" if asset_index == len(tokens) else ("SUBJECT" if asset_index == 1 else "OBJECT"),
                "semantic_intent": "EXPLAIN",
                "narrative_function": "BIND_SEMANTIC_ASSET_INTENT",
                "binding_type": binding_type,
                "script_text": token,
                "script_span": {"text": token, **span},
                "appear_trigger": {"text": token, **span},
                "focus_trigger": {"text": None, "global_char_start": None, "global_char_end": None},
                "exit_trigger": {"text": None, "global_char_start": None, "global_char_end": None},
                "semantic_group_id": group_id,
                "sequence_order": asset_index,
                "parent_asset_id": parent_by_asset[asset_id],
                "children_asset_ids": parent_children.get(asset_id, []),
                "confidence": 0.99,
                "interaction_target": None,
                "relationship": None,
                "semantic_event_id": event_id,
                "anchor_granularity": "EXACT_WORD",
                "visual_focus": "RESULT" if asset_index == len(tokens) else ("PRIMARY" if asset_index == 1 else "SUPPORT"),
                "visual_state": {"before": None, "after": None},
                "continuity": continuity,
                "compound_visual_classification": "COMPOUND_REQUIRED" if shape.compound and asset_index == len(tokens) else "SEPARABLE_SAFE",
                "internal_progression_unavailable": bool(shape.compound and asset_index == len(tokens)),
                "needs_review": False,
                "ambiguity_reason": None,
                "visual_locator": locator,
            }
            objects.append(obj)
            deps: list[str] = []
            if shape.dependencies and shape.dependency_mode != "none" and asset_index > 1:
                deps = [f"{scene_id}_E01"] if shape.dependency_mode == "branching" else [f"{scene_id}_E{asset_index - 1:02d}"]
            participants = [f"{scene_id}_A01"] if shape.reuse_first_asset and asset_index > 1 else []
            events.append({
                "semantic_event_id": event_id,
                "scene_id": scene_id,
                "script_text": token,
                "script_span": {"text": token, **span},
                "anchor_granularity": "EXACT_WORD",
                "sequence_order": asset_index,
                "visual_leader_asset_id": asset_id,
                "participant_asset_ids": participants,
                "context_asset_ids": [],
                "result_asset_ids": [asset_id] if asset_index == len(tokens) else [],
                "text_anchor_asset_id": asset_id,
                "confidence": 0.99,
                "needs_review": False,
                "ambiguity_reason": None,
                "depends_on_event_ids": deps,
            })
            if shape.relations and asset_index > 1:
                previous = f"{scene_id}_A{asset_index - 1:02d}"
                relation_text = f"{tokens[asset_index - 2]} {token}"
                relation_start = _disk_span(script, tokens[asset_index - 2], scene_start)["global_char_start"]
                relations.append({
                    "relation_id": f"{scene_id}_R{asset_index - 1:02d}",
                    "subject_asset_id": previous,
                    "relation_type": "ENABLES",
                    "relationship": "ENABLES",
                    "object_asset_id": asset_id,
                    "result_asset_id": None,
                    "connector_asset_id": None,
                    "script_text": relation_text,
                    "script_span": {"text": script[relation_start:span["global_char_end"]], "global_char_start": relation_start, "global_char_end": span["global_char_end"]},
                    "confidence": 0.97,
                })

        groups = []
        for group_index in range(1, group_count + 1):
            group_id = f"{scene_id}_G{group_index:02d}"
            members = [row["asset_id"] for row in objects if row["semantic_group_id"] == group_id]
            groups.append({
                "semantic_group_id": group_id,
                "script_text": phrase,
                "animation_policy": shape.group_policy,
                "asset_ids": members,
            })
        scene_rows.append({
            "scene_id": scene_id,
            "order": scene_index - 1,
            "image": image_rel,
            "title": None,
            "narration_hint": phrase,
            "script_span": {"text": phrase, "global_char_start": scene_start, "global_char_end": scene_end},
            "purpose": "EXPLAIN",
            "visual_concept": f"concept {scene_index}",
            "relation_to_previous": None if scene_index == 1 else "CONTINUES_NARRATIVE",
            "character_category": None,
            "objects": objects,
            "visual_progression": [],
            "semantic_groups": groups,
            "semantic_events": events,
            "relations": relations,
            "semantic_progression": {
                "type": "GENERIC_PROGRESS" if shape.progression and events else None,
                "event_order": [row["semantic_event_id"] for row in events] if shape.progression else [],
            },
        })

    payload = {
        "contract": "HEXA_UNIFIED_FINAL_PACKAGE",
        "contract_version": "2.0",
        "package_id": f"test1-generated-{shape.namespace or 'default'}",
        "project_slug": f"test1-generated-{shape.namespace or 'default'}",
        "language": "ar" if shape.script_style in {"arabic", "numbers"} else "en",
        "builder_target": "HEXA_VIDEO_BUILDER_V20",
        "timing_authority": "FINAL_VOICE_OVER_SEPARATE_INPUT",
        "script_audio_relationship": "EXACT_MATCH",
        "canonical_script": script,
        "image_spec": {"directory": "images", "format": "png", "width": 64, "height": 64},
        "source_provenance": {
            "source_contract_version": "2.0",
            "source_package_name": "generated-test",
            "source_sha256": "0" * 64,
            "conversion_mode": "NATIVE_UNIFIED_TEST",
        },
        "scenes": scene_rows,
    }
    (package / "package.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return package

def seeded_disk_shape(seed: int) -> DiskPackageShape:
    rng = random.Random(seed)
    return DiskPackageShape(
        scenes=rng.randint(1, 5),
        assets_per_scene=rng.randint(1, 8),
        relations=rng.choice([True, False]),
        dependencies=rng.choice([True, False]),
        dependency_mode=rng.choice(["none", "linear", "branching"]),
        locators=rng.choice(["none", "partial", "all"]),
        extra_metadata=rng.choice([True, False]),
        compound=rng.choice([True, False]),
        progression=rng.choice([True, False]),
        group_count=rng.choice([1, 1, 2]),
        group_policy=rng.choice([
            "SEQUENTIAL_WITHIN_PHRASE", "SIMULTANEOUS_VISUAL_UNIT"
        ]),
        binding_types=rng.choice([
            ("EXPLICIT", "SEMANTIC"),
            ("EXPLICIT", "SUPPORT"),
            ("SEMANTIC", "AMBIGUOUS"),
            ("EXPLICIT", "PARENT", "SEMANTIC"),
        ]),
        continuity=rng.choice(["none", "persist", "transform"]),
        reuse_first_asset=rng.choice([True, False]),
        script_style=rng.choice(["ascii", "arabic", "numbers"]),
        namespace=f"N{seed}",
    )


def deterministic_transcript(package) -> "Transcript":
    """Create a stable forced-alignment-like clock for structural planning tests."""
    import re
    from app.models import TranscriptSegment, TranscriptWord

    script = package.script or ""
    words: list[TranscriptWord] = []
    for index, match in enumerate(re.finditer(r"\S+", script)):
        # Deliberately comfortable speech cadence for structural planning. The goal is
        # to exercise semantic scheduling, not simulate a fast narrator that makes
        # otherwise valid authored interactions physically infeasible.
        start = 0.30 + index * 0.42
        end = start + 0.28
        words.append(TranscriptWord(
            text=match.group(0),
            start=start,
            end=end,
            char_start=match.start(),
            char_end=match.end(),
        ))
    duration = (words[-1].end + 0.30) if words else 1.0
    segments: list[TranscriptSegment] = []
    for scene in package.scenes:
        start_char = scene.script_char_start
        end_char = scene.script_char_end
        scene_words = [
            word for word in words
            if start_char is not None
            and end_char is not None
            and word.char_end is not None
            and word.char_start is not None
            and word.char_end > start_char
            and word.char_start <= end_char
        ]
        if not scene_words:
            continue
        text = script[start_char:end_char + 1] if script else " ".join(w.text for w in scene_words)
        segments.append(TranscriptSegment(
            start=scene_words[0].start,
            end=scene_words[-1].end,
            text=text.strip() or "scene",
            char_start=start_char,
            char_end=end_char + 1,
            words=scene_words,
        ))
    return Transcript(
        language="en",
        duration=duration,
        segments=segments,
        words=words,
        timing_source="forced_alignment",
    )


def controlled_visual_assets(package) -> list["VisualAsset"]:
    """Create deterministic runtime cutouts that preserve canonical asset identity."""
    from math import ceil, sqrt

    output: list[VisualAsset] = []
    for scene in package.scenes:
        semantic_assets = list(scene.assets)
        count = max(1, len(semantic_assets))
        columns = max(1, ceil(sqrt(count)))
        rows = max(1, ceil(count / columns))
        cell_w = 900 / columns
        cell_h = 900 / rows
        for index, asset in enumerate(semantic_assets):
            col = index % columns
            row = index // columns
            x = int(50 + col * cell_w + cell_w * 0.15)
            y = int(50 + row * cell_h + cell_h * 0.15)
            width = max(24, int(cell_w * 0.55))
            height = max(24, int(cell_h * 0.55))
            output.append(VisualAsset(
                id=asset.asset_id,
                scene_id=scene.id,
                role=str(asset.role or asset.semantic_role or "object").lower(),
                image_path=scene.image_path,
                source_bbox=(x, y, width, height),
                source_canvas_width=1000,
                source_canvas_height=1000,
                source_area_ratio=min(0.95, (width * height) / 1_000_000),
                extraction_method="test1-controlled",
                parent_asset_id=asset.parent_asset_id,
                compound=bool(asset.internal_progression_unavailable),
                can_animate_independently=not bool(asset.internal_progression_unavailable),
            ))
    return output
