from __future__ import annotations

from enum import StrEnum


class BindingType(StrEnum):
    EXPLICIT = "EXPLICIT"
    SEMANTIC = "SEMANTIC"
    SUPPORT = "SUPPORT"
    PARENT = "PARENT"
    AMBIGUOUS = "AMBIGUOUS"


class VisualFocus(StrEnum):
    PRIMARY = "PRIMARY"
    SUPPORT = "SUPPORT"
    RESULT = "RESULT"
    CONTEXT = "CONTEXT"


class AnchorGranularity(StrEnum):
    EXACT_WORD = "EXACT_WORD"
    EXACT_PHRASE = "EXACT_PHRASE"
    SCENE_PHRASE = "SCENE_PHRASE"


class SemanticGroupAnimationPolicy(StrEnum):
    SEQUENTIAL_WITHIN_PHRASE = "SEQUENTIAL_WITHIN_PHRASE"
    SIMULTANEOUS_VISUAL_UNIT = "SIMULTANEOUS_VISUAL_UNIT"


class CompoundVisualClassification(StrEnum):
    SEPARABLE_SAFE = "SEPARABLE_SAFE"
    COMPOUND_REQUIRED = "COMPOUND_REQUIRED"


class ContinuityMode(StrEnum):
    PERSIST = "PERSIST"
    TRANSFORM_TO = "TRANSFORM_TO"
