from __future__ import annotations

from app.models import TextStyle
from app.text.style.presets import default_text_styles
from app.text.timing import TimedKeyword


class TextStyleResolver:
    def __init__(self, styles: dict[str, TextStyle] | None = None) -> None:
        self.styles = styles or default_text_styles()

    def resolve(self, keyword: TimedKeyword) -> TextStyle:
        style_id = keyword.candidate.semantic_type
        return self.styles.get(style_id, self.styles["keyword"])
