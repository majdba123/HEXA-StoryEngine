from __future__ import annotations

from enum import StrEnum


class CanonicalAuthority(StrEnum):
    MANIFEST = "manifest"
    SCENE_PLAN = "scene_plan"
    SEMANTIC_BINDINGS = "semantic_bindings"
    CANONICAL_SCRIPT = "canonical_script"


AUTHORITY_MATRIX = {
    "script": CanonicalAuthority.CANONICAL_SCRIPT,
    "scene_order": CanonicalAuthority.SCENE_PLAN,
    "scene_image": CanonicalAuthority.SCENE_PLAN,
    "semantic_asset": CanonicalAuthority.SEMANTIC_BINDINGS,
    "semantic_event": CanonicalAuthority.SEMANTIC_BINDINGS,
    "semantic_relation": CanonicalAuthority.SEMANTIC_BINDINGS,
    "visual_locator": CanonicalAuthority.SEMANTIC_BINDINGS,
}
