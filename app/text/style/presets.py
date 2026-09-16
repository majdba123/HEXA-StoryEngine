from __future__ import annotations

from app.models import TextStyle


def default_text_styles() -> dict[str, TextStyle]:
    """Logical design tokens; final font assets/colors are resolved at render-product level."""
    styles = [
        TextStyle(
            id="keyword",
            role="keyword",
            font_role="display",
            size_role="medium",
            color_role="primary",
            background_role="none",
            emphasis_role="standard",
        ),
        TextStyle(
            id="number",
            role="number",
            font_role="display",
            size_role="large",
            color_role="primary",
            background_role="none",
            emphasis_role="numeric",
        ),
        TextStyle(
            id="amount",
            role="amount",
            font_role="display",
            size_role="large",
            color_role="primary",
            background_role="none",
            emphasis_role="numeric",
        ),
        TextStyle(
            id="warning_amount",
            role="warning_amount",
            font_role="display",
            size_role="large",
            color_role="warning",
            background_role="soft_warning",
            emphasis_role="warning",
        ),
        TextStyle(
            id="warning",
            role="warning",
            font_role="display",
            size_role="large",
            color_role="warning",
            background_role="none",
            emphasis_role="warning",
        ),
        TextStyle(
            id="emphasis",
            role="emphasis",
            font_role="display",
            size_role="medium",
            color_role="accent",
            background_role="none",
            emphasis_role="strong",
        ),
    ]
    return {style.id: style for style in styles}
