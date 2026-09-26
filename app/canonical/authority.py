from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Any


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



def resolve_semantic_record(
    structural: Mapping[str, Any] | None,
    semantic: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Resolve one record using the canonical authority contract.

    Scene-plan data is the structural fallback. When semantic-bindings provide the
    same field, they are authoritative for semantic facts. Keeping this merge in one
    module prevents individual downstream layers from choosing their own source.
    """

    resolved = dict(structural or {})
    resolved.update(semantic or {})
    return resolved


def resolve_semantic_collection(structural: Any, semantic: Any) -> Any:
    """Prefer an explicitly authored semantic collection, otherwise use structure."""

    return semantic if isinstance(semantic, list) else structural


def resolve_semantic_mapping(structural: Any, semantic: Any) -> Any:
    """Prefer an explicitly authored semantic mapping, otherwise use structure."""

    return semantic if isinstance(semantic, Mapping) else structural
