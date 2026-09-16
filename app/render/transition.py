from __future__ import annotations

from dataclasses import dataclass

from app.models import CompositionBeat, StoryBeat


@dataclass(frozen=True, slots=True)
class VisualTransitionDecision:
    persistent_asset_ids: frozenset[str]
    carry_outgoing_asset_ids: frozenset[str]


class VisualTransitionPolicy:
    """Prevent cross-beat ghosting while preserving true persistent artwork.

    Cutout-style explainer scenes are rendered on white. Alpha crossfading a previous
    full-colour object underneath a new entrance turns it into a washed-out silhouette,
    which reads as a segmentation ghost. We therefore never carry unrelated outgoing
    artwork. Assets that genuinely persist keep their current-layer pixels visible from
    frame zero instead of being duplicated as fading old/new copies.
    """

    def decide(
        self,
        previous_beat: StoryBeat | None,
        previous_layout: CompositionBeat | None,
        current_layout: CompositionBeat | None,
    ) -> VisualTransitionDecision:
        del previous_beat
        previous_ids = {
            item.asset_id for item in previous_layout.items
        } if previous_layout is not None else set()
        current_ids = {
            item.asset_id for item in current_layout.items
        } if current_layout is not None else set()
        persistent = frozenset(previous_ids & current_ids)
        # Deliberately empty: unrelated outgoing layers are a visual contaminant for
        # this graphic style. Incoming primaries start at the beat boundary, so there
        # is no need to hide a blank frame with a faded previous composition.
        return VisualTransitionDecision(
            persistent_asset_ids=persistent,
            carry_outgoing_asset_ids=frozenset(),
        )
