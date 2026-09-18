from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SceneDirection:
    beat_id: str
    primary_asset_id: str | None
    interaction_asset_id: str | None
    active_asset_ids: tuple[str, ...]
    layout_intent: str
    motion_intent: str
    text_intent: str
    evidence: tuple[str, ...] = ()
