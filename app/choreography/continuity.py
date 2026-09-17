from __future__ import annotations

from dataclasses import dataclass

from app.models import StoryBeat

from .models import ContinuityMode


@dataclass(frozen=True, slots=True)
class ContinuityDecision:
    from_asset_id: str | None
    mode: ContinuityMode


class ContinuityResolver:
    """Describe visual continuity without taking placement ownership from Composition."""

    @staticmethod
    def decide(previous: StoryBeat | None, current: StoryBeat) -> ContinuityDecision:
        """Backward-compatible story-primary continuity for callers without binding."""
        previous_primary = previous.primary_asset_ids[0] if previous and previous.primary_asset_ids else None
        current_primary = current.primary_asset_ids[0] if current.primary_asset_ids else None
        current_ids = set(current.primary_asset_ids + current.support_asset_ids)
        return ContinuityResolver.decide_focus(previous_primary, current_primary, current_ids)

    @staticmethod
    def decide_focus(
        previous_focus: str | None,
        current_focus: str | None,
        current_asset_ids: set[str] | frozenset[str],
    ) -> ContinuityDecision:
        if previous_focus is None or current_focus is None:
            return ContinuityDecision(None, ContinuityMode.NONE)
        if previous_focus == current_focus and previous_focus in current_asset_ids:
            return ContinuityDecision(previous_focus, ContinuityMode.SAME_ASSET)
        if previous_focus != current_focus:
            return ContinuityDecision(previous_focus, ContinuityMode.SEMANTIC_HANDOFF)
        return ContinuityDecision(None, ContinuityMode.NONE)
