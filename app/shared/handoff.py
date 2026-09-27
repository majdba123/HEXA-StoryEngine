from __future__ import annotations

from .handoff_choreography import ChoreographyCompositionHandoffMixin
from .handoff_motion import MotionHandoffMixin
from .handoff_story import AssetStoryHandoffMixin
from .handoff_text import TextHandoffMixin


class LayerHandoffValidator(
    AssetStoryHandoffMixin,
    ChoreographyCompositionHandoffMixin,
    MotionHandoffMixin,
    TextHandoffMixin,
):
    """Production producer -> consumer handoff contracts.

    The facade keeps one stable API while boundary-specific validators remain isolated
    and maintainable. No semantic ownership moves into this layer.
    """

    pass
