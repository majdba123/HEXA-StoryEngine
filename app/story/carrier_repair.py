"""Repair instead of stopping when a carrier audit finds authored content hidden.

The carrier audits (``SemanticCarrierAuditor``) prove that every required authored element
keeps a visible carrier and that no significant authored cutout is dropped. They used to
stop the render. A render that stops helps nobody (user direction 2026-10-21), and every
finding here has a safe visual answer: show the hidden cutout. It appears exactly when a
cutout already carrying the same authored unit appears (the rest of the same drawing),
else with the scene's first visible element. The audits then run again on the repaired
Story; whatever they still report is recorded, and only contested ownership between
cutouts that are now all visible is accepted as a warning. Every repair is logged.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from app.models import StoryBeat

STORY_CARRIER_REPAIR = True
_REPAIRABLE = frozenset({"UNRESOLVED", "HIDDEN", "AMBIGUOUS"})


def _abstained(row) -> bool:
    return (getattr(row, "activation_policy", None) == "SAFE_ABSTENTION"
            or getattr(row, "policy", None) in {"SAFE_ABSTENTION", "FALLBACK"})


def assets_to_reveal(carrier_records: list[dict[str, Any]],
                     hidden_records: list[dict[str, Any]]) -> dict[str, dict[str, str | None]]:
    """scene id -> {hidden runtime asset id: the authored unit it belongs to (or None)}."""
    reveal: dict[str, dict[str, str | None]] = defaultdict(dict)
    for row in carrier_records:
        if row.get("status") not in _REPAIRABLE:
            continue
        ids = row.get("candidate_hidden_asset_ids") or []
        if row.get("status") == "HIDDEN":
            ids = row.get("carrier_asset_ids") or ids
        for asset_id in ids:
            reveal[row["scene_id"]].setdefault(asset_id, row.get("semantic_asset_id"))
    for row in hidden_records:
        mapping = row.get("runtime_mapping") or {}
        reveal[row["scene_id"]].setdefault(row["runtime_asset_id"], mapping.get("semantic_unit_id"))
    return reveal


def reveal_assets(beats: list[StoryBeat],
                  reveal: dict[str, dict[str, str | None]]) -> tuple[list[StoryBeat], list[dict[str, Any]]]:
    """Give every asset to reveal a visible activation copied from its template."""
    by_scene: dict[str, list[int]] = defaultdict(list)
    for index, beat in enumerate(beats):
        by_scene[beat.scene_id].append(index)
    output = list(beats)
    repairs: list[dict[str, Any]] = []
    for scene_id, assets in reveal.items():
        positions = by_scene.get(scene_id, [])
        if not positions:
            continue
        visible = [(position, row) for position in positions for row in output[position].asset_activations
                   if not _abstained(row)]
        if not visible:
            continue
        opener_position, opener = min(visible, key=lambda pair: (
            pair[1].spoken_start if pair[1].spoken_start is not None else float("inf"), pair[1].asset_id))
        for asset_id, unit_id in sorted(assets.items()):
            sibling = next(((position, row) for position, row in visible
                            if unit_id and row.semantic_unit_id == unit_id and row.asset_id != asset_id), None)
            position, template = sibling or (opener_position, opener)
            home = next((p for p in positions if any(r.asset_id == asset_id for r in output[p].asset_activations)),
                        position)
            revealed = template.model_copy(update={
                "asset_id": asset_id,
                "semantic_unit_id": unit_id or template.semantic_unit_id,
                "source": "carrier_repair",
                "evidence": ["revealed_hidden_authored_cutout",
                             "with_unit_sibling" if sibling else "with_scene_opener"],
            })
            rows = [row for row in output[home].asset_activations if row.asset_id != asset_id]
            output[home] = output[home].model_copy(update={"asset_activations": [*rows, revealed]})
            repairs.append({"scene_id": scene_id, "asset_id": asset_id, "unit_id": unit_id,
                            "timing_from": template.asset_id, "rule": "sibling" if sibling else "scene_opener"})
    return output, repairs


def tolerable(record: dict[str, Any]) -> bool:
    """Contested ownership is acceptable once every contested cutout is on screen."""
    if record.get("status") != "AMBIGUOUS":
        return False
    visible = set(record.get("visible_scene_asset_ids") or [])
    contested = set(record.get("carrier_asset_ids") or []) | set(record.get("candidate_hidden_asset_ids") or [])
    return bool(contested) and contested <= visible
