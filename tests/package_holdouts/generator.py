from __future__ import annotations

import json
import random
import zipfile
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw

from tests.package_holdouts.cases import BLACK_HAT_PROFILE, HoldoutCase
from tests.support.unified_package import write_unified_package


@dataclass(frozen=True, slots=True)
class GeneratedPackage:
    case: HoldoutCase
    root: Path
    features: tuple[str, ...]


def profile_from_black_hat(zip_path: Path) -> dict[str, int]:
    """Derive the generation authority directly from the certified package."""
    with zipfile.ZipFile(zip_path) as archive:
        payload = json.loads(archive.read("package.json"))
    scenes = payload["scenes"]
    return {
        "scenes": len(scenes),
        "objects": sum(len(row["objects"]) for row in scenes),
        "semantic_groups": sum(len(row["semantic_groups"]) for row in scenes),
        "semantic_events": sum(len(row["semantic_events"]) for row in scenes),
        "relations": sum(len(row["relations"]) for row in scenes),
    }


def assert_black_hat_profile(zip_path: Path) -> None:
    assert profile_from_black_hat(zip_path) == BLACK_HAT_PROFILE


def _art(path: Path, size: tuple[int, int], boxes: list[tuple[int, int, int, int]], seed: int) -> None:
    rng = random.Random(seed)
    image = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(image)
    for index, (x, y, w, h) in enumerate(boxes):
        colour = (40 + (index * 61) % 180, 55 + (index * 83) % 170, 70 + (index * 47) % 160)
        draw.rounded_rectangle((x, y, x + w, y + h), radius=max(2, min(w, h) // 8), fill=colour, outline="black", width=2)
        if rng.random() < 0.6:
            draw.line((x + 3, y + h // 2, x + w - 3, y + h // 2), fill="white", width=2)
    image.save(path)


def generate(case: HoldoutCase, root: Path) -> GeneratedPackage:
    separators = (" ", "\n", "\r\n", "\u00a0")
    phrases = [f"unit{case.seed}_{i} acts result{i}" for i in range(case.scene_count)]
    script = "".join((separators[i % len(separators)] if i else "") + value for i, value in enumerate(phrases))
    scenes = []
    cursor = 0
    for index, phrase in enumerate(phrases):
        if index:
            cursor += len(separators[index % len(separators)])
        start, end = cursor, cursor + len(phrase)
        cursor = end
        scene_id = f"S{case.seed}_{index:03d}"
        count = 1 if case.family == "sparse" else (5 if case.family == "dense" else 3)
        event_id = f"{scene_id}_E0"
        objects = []
        boxes = []
        for object_index in range(count):
            col = object_index % 3
            row = object_index // 3
            w, h = 54, 48
            x = 0 if case.family == "edge_locators" and object_index == 0 else 18 + col * 92
            y = 0 if case.family == "edge_locators" and object_index == 0 else 18 + row * 70
            if case.family == "close_locators" and object_index:
                # Deliberately close (six-pixel gaps), but still uniquely separable.
                x = 74 + (object_index - 1) * 60
                y = 55
            boxes.append((x, y, w, h))
            locator = {"coordinate_space": "normalized_scene", "cx": (x + w / 2) / 320, "cy": (y + h / 2) / 180, "width": w / 320, "height": h / 180}
            objects.append({
                "asset_id": f"{scene_id}_A{object_index}",
                "role": "primary" if object_index == 0 else "supporting",
                "semantic_role": "PRIMARY" if object_index == 0 else "SUPPORT",
                "script_text": phrase,
                "script_span": {"global_char_start": start, "global_char_end": end, "text": phrase},
                "appear_trigger": {"global_char_start": start, "global_char_end": end, "text": phrase},
                "semantic_group_id": f"{scene_id}_G",
                "semantic_event_id": event_id,
                "sequence_order": object_index + 1,
                "visual_locator": locator,
            })
        events = [{
            "semantic_event_id": event_id,
            "script_text": phrase,
            "script_span": {"global_char_start": start, "global_char_end": end, "text": phrase},
            "sequence_order": 1,
            "visual_leader_asset_id": objects[0]["asset_id"],
            "participant_asset_ids": [row["asset_id"] for row in objects[1:-1]],
            "result_asset_ids": [objects[-1]["asset_id"]] if len(objects) > 1 else [],
            "text_anchor_asset_id": objects[0]["asset_id"],
        }]
        relations = []
        if case.family not in {"sparse", "no_relations"} and len(objects) > 1:
            relations.append({
                "relation_id": f"{scene_id}_R0", "subject_asset_id": objects[0]["asset_id"],
                "relation_type": "CAUSES", "object_asset_id": objects[-1]["asset_id"],
                "script_text": phrase,
                "script_span": {"global_char_start": start, "global_char_end": end, "text": phrase},
            })
        scenes.append({
            "scene_id": scene_id, "order": index,
            "script_span": {"global_char_start": start, "global_char_end": end, "text": phrase},
            "objects": objects,
            "semantic_groups": [{"semantic_group_id": f"{scene_id}_G", "script_text": phrase, "asset_ids": [row["asset_id"] for row in objects]}],
            "semantic_events": events, "relations": relations,
            "semantic_progression": {"type": "CAUSE_ACTION_RESULT", "event_order": [event_id]} if case.family != "no_progression" else {},
        })
    package = write_unified_package(root, script=script, scenes=scenes, package_id=f"holdout-{case.seed}", image_size=(320, 180))
    for index, scene in enumerate(scenes):
        image = package / "images" / f"{scene['scene_id']}.png"
        size = (320, 180)
        if case.image_mode == "same_aspect" or (case.image_mode == "one_mismatch" and index == 0):
            size = (640, 360)
        elif case.image_mode == "fit_pad":
            size = (320, 240)
        scale_x, scale_y = size[0] / 320, size[1] / 180
        scaled = [(round(x * scale_x), round(y * scale_y), round(w * scale_x), round(h * scale_y)) for x, y, w, h in boxes]
        _art(image, size, scaled, case.seed + index)
    return GeneratedPackage(case, package, (case.family, case.image_mode, "half_open_spans", "unicode_whitespace"))
