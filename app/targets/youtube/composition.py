from __future__ import annotations

from app.choreography import ChoreographyDirective
from app.models import LayoutItem, VisualAsset
from app.targets.models import TargetProjection


class YouTubeCompositionPolicy:
    """16:9 is the authored reference frame: the Final Package geometry is kept as is.

    The shared CompositionPlanner already contain-fits each authored scene into 16:9, so
    the YouTube projection is the identity. Returning the same list keeps the certified
    Sprint 4/5 Composition byte-for-byte.
    """

    def project(
        self,
        items: list[LayoutItem],
        assets: list[VisualAsset],
        directives: list[ChoreographyDirective],
    ) -> TargetProjection:
        return TargetProjection(items=items, evidence="target:YOUTUBE_16_9:authored_reference")
