"""Pass2 families that move as one rigid unit (Cinematic VNext2).

A Pass2 family is one picture split into layers: its secondary layers are geometry-locked
to the authored footprint. When every layer shares the primary's Composition box and its
Story clock, the family can take any gesture as one unit: Motion plans the gesture on the
primary only and marks each secondary ``family_follow``; the renderer then draws that
secondary with the primary's own transform (identical box, identical expression, so the
layers stay pixel-aligned). Anything else keeps the certified locked reveal.
"""
from __future__ import annotations

from copy import deepcopy

from app.assets import AssetManager
from app.models import LayoutItem, MotionCue, VisualAsset

FOLLOW_PARAM = "family_follow"
_EPS = 1e-6


def family_of(asset_id: str, assets_by_id: dict[str, VisualAsset]) -> str:
    asset = assets_by_id.get(asset_id)
    return AssetManager.family_id(asset) if asset is not None else asset_id


def rigid_followers(
    cue: MotionCue,
    beat_cues: list[MotionCue],
    layout: dict[str, LayoutItem],
    assets_by_id: dict[str, VisualAsset],
) -> list[MotionCue] | None:
    """The secondaries that follow ``cue`` as one rigid unit: [] for a single asset, None
    when ``cue`` is not the primary of a family that can move as one."""
    family = family_of(cue.asset_id, assets_by_id)
    members = [row for row in beat_cues
               if row.asset_id != cue.asset_id and family_of(row.asset_id, assets_by_id) == family]
    if not members:
        return []
    if cue.asset_id != family:
        return None  # only the primary leads its family
    lead = layout.get(cue.asset_id)
    if lead is None:
        return None
    for row in members:
        item = layout.get(row.asset_id)
        params = row.params if isinstance(row.params, dict) else {}
        if item is None or any(abs(float(getattr(item, key)) - float(getattr(lead, key))) > _EPS
                               for key in ("x", "y", "width", "height")):
            return None
        if abs(float(row.start) - float(cue.start)) > _EPS or abs(float(row.end) - float(cue.end)) > _EPS:
            return None
        if (params.get("semantic_continuity") or {}).get("mode", "ENTER") != "ENTER":
            return None
        if any(segment.phase != "ENTRY" for segment in row.segments):
            return None
    return members


def follow(member: MotionCue, leader: MotionCue) -> MotionCue:
    """``member`` drawn with ``leader``'s transform, on ``leader``'s clock."""
    params = dict(member.params)
    params[FOLLOW_PARAM] = leader.asset_id
    if isinstance(leader.params.get("entry_opacity"), dict):
        params["entry_opacity"] = deepcopy(leader.params["entry_opacity"])
    else:
        params.pop("entry_opacity", None)
    grammar = dict(params.get("entry_grammar") or {})
    grammar["arrival"] = "FOLLOW"
    leader_grammar = leader.params.get("entry_grammar") or {}
    if "opacity" in leader_grammar:
        grammar["opacity"] = leader_grammar["opacity"]
    params["entry_grammar"] = grammar
    return member.model_copy(update={"params": params, "start": leader.start, "end": leader.end})


def bind_families(
    motion: list[MotionCue],
    layouts: dict[str, dict[str, LayoutItem]],
    assets_by_id: dict[str, VisualAsset],
) -> list[MotionCue]:
    """Mark every geometry-locked Pass2 layer that shares its primary's Composition box so
    the renderer draws it with the primary's transform (its own clock is kept)."""
    present = {(cue.beat_id, cue.asset_id) for cue in motion}
    output = []
    for cue in motion:
        params = cue.params if isinstance(cue.params, dict) else {}
        primary = family_of(cue.asset_id, assets_by_id)
        layout = layouts.get(cue.beat_id, {})
        item, lead = layout.get(cue.asset_id), layout.get(primary)
        if (primary != cue.asset_id and (params.get("render_constraints") or {}).get("geometry_lock")
                and (cue.beat_id, primary) in present and item is not None and lead is not None
                and all(abs(float(getattr(item, key)) - float(getattr(lead, key))) <= _EPS
                        for key in ("x", "y", "width", "height"))):
            if params.get(FOLLOW_PARAM) != primary:
                cue = cue.model_copy(update={"params": {**params, FOLLOW_PARAM: primary}})
        output.append(cue)
    return output
