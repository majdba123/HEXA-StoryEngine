from __future__ import annotations

from typing import Iterable

from app.models import StoryBeat, VisualAsset
from app.story.binding import SemanticAssetBinder

from .models import EventFlowStage, SemanticEventFlow


_FOCUS_STAGES = {
    EventFlowStage.ESTABLISH,
    EventFlowStage.ADD,
    EventFlowStage.INTERACT,
    EventFlowStage.REACT,
}
# One leader plus one participating character is the most a clean frame can carry.
_MAX_EMPHASIZED_CHARACTERS = 2


def select_character_emphasis(
    beat: StoryBeat,
    assets: Iterable[VisualAsset],
    event_flows: tuple[SemanticEventFlow, ...],
) -> tuple[str, ...]:
    """Name the authored scene characters whose semantic event is currently about them.

    Evidence only: a character qualifies when a Final Package event flow makes it the
    focus (or a source/target) of an ESTABLISH/ADD/INTERACT/REACT step. Characters that are
    merely present, RESULT assets, and anything the package does not type as a character
    are never selected. Without event flows there is no evidence, so nothing is
    emphasized. Choreography only says WHO; Motion decides how much, and Composition
    keeps final geometry.
    """
    if not event_flows:
        return ()
    scene_assets = [asset for asset in assets if asset.scene_id == beat.scene_id]
    visible = set(beat.primary_asset_ids) | set(beat.support_asset_ids)
    characters = {
        asset_id
        for asset_id in SemanticAssetBinder.authored_character_assets(beat, scene_assets)
        if asset_id in visible
    }
    if not characters:
        return ()

    results = {
        asset_id
        for flow in event_flows
        for asset_id in flow.result_asset_ids
    } | {
        step.result_asset_id
        for flow in event_flows
        for step in flow.steps
        if step.result_asset_id
    }
    ordered_flows = sorted(
        event_flows,
        key=lambda flow: (flow.order if flow.order is not None else 10_000, flow.event_id),
    )
    selected: list[str] = []
    for flow in ordered_flows:
        for step in flow.steps:
            if step.stage not in _FOCUS_STAGES:
                continue
            for asset_id in (step.focus_asset_id, step.source_asset_id, step.target_asset_id):
                if (
                    asset_id in characters
                    and asset_id not in results
                    and asset_id not in selected
                ):
                    selected.append(asset_id)
    return tuple(selected[:_MAX_EMPHASIZED_CHARACTERS])
