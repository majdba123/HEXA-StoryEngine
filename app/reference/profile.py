from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class HexaVisualProfile:
    """Hard visual constraints extracted from the approved HEXA editing references."""

    max_standard_elements: int = 4
    safe_left: float = 0.04
    safe_right: float = 0.96
    safe_top: float = 0.05
    safe_bottom: float = 0.95
    minimum_directional_frames: int = 12
    max_unintended_overlap_ratio: float = 0.22
    catastrophic_overlap_ratio: float = 0.52
    minimum_visible_gap: float = 0.018
    reference_names: tuple[str, ...] = (
        "hallo 2.mp4",
        "تأثير المتفرج2.mp4",
        "انحياز 2.mp4",
    )

    @classmethod
    def production(cls) -> "HexaVisualProfile":
        return cls()
