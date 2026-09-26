from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TextLayoutContract:
    """Composition-owned hard acceptance limits for authored text placement."""

    max_visual_overlap: float = 0.012
    max_text_overlap: float = 0.04

    def accepts(self, *, visual_overlap: float, text_overlap: float) -> bool:
        return (
            float(visual_overlap) <= self.max_visual_overlap + 1e-12
            and float(text_overlap) <= self.max_text_overlap + 1e-12
        )
