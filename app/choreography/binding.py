"""Compatibility export for semantic asset binding.

Semantic unit to cutout binding belongs to Story. Choreography imports the same
implementation so existing choreography behavior remains unchanged.
"""

from app.story.binding import AssetBinding, SemanticAssetBinder

__all__ = ["AssetBinding", "SemanticAssetBinder"]
