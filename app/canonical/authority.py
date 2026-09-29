from __future__ import annotations

from enum import StrEnum


class CanonicalAuthority(StrEnum):
    UNIFIED_FINAL_PACKAGE = "unified_final_package"
    FORCED_ALIGNMENT = "forced_alignment"
    COMPOSITION = "composition"
    MOTION = "motion"


AUTHORITY_MATRIX = {
    "script": CanonicalAuthority.UNIFIED_FINAL_PACKAGE,
    "scene_order": CanonicalAuthority.UNIFIED_FINAL_PACKAGE,
    "scene_image": CanonicalAuthority.UNIFIED_FINAL_PACKAGE,
    "semantic_asset": CanonicalAuthority.UNIFIED_FINAL_PACKAGE,
    "semantic_event": CanonicalAuthority.UNIFIED_FINAL_PACKAGE,
    "semantic_relation": CanonicalAuthority.UNIFIED_FINAL_PACKAGE,
    "visual_locator": CanonicalAuthority.UNIFIED_FINAL_PACKAGE,
}
