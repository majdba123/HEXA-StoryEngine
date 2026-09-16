from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.models import RenderPlan, StoryBeat, TextLayoutItem, TextMotionCue


@dataclass(frozen=True, slots=True)
class TextRenderTheme:
    """High-contrast explainer-title tokens for sparse keyword storytelling."""

    font_family: str = "Noto Kufi Arabic"
    primary: str = "&H00452B16"      # dark navy, ASS AABBGGRR
    accent: str = "&H00EB6E0A"       # saturated HEXA-style blue
    gold: str = "&H001AA4F2"         # warm gold for numbers
    warning: str = "&H003F4BE3"      # warm red
    outline: str = "&H00FFFFFF"       # white separation from detailed artwork
    shadow: str = "&H500D1826"        # translucent navy depth


class TextRenderer:
    """Render shaped RTL/LTR sparse keywords through libass/HarfBuzz/FriBidi.

    A multi-word cue is one stable ASS line, not a sequence of recentered subtitle
    fragments. Future words are laid out invisibly from the cue's first frame and each
    word reveals at its exact forced-alignment timestamp. This keeps the final phrase
    geometry stable while producing authored word-by-word storytelling motion.
    """

    def __init__(self, *, font_family: str = "Noto Kufi Arabic") -> None:
        self.theme = TextRenderTheme(font_family=font_family)
