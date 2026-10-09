from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from app.canonical import (
    AnchorGranularity,
    BindingType,
    CanonicalAsset,
    CanonicalContinuity,
    CanonicalPackage,
    CanonicalProgression,
    CanonicalRelation,
    CanonicalScene,
    CanonicalScriptSpan,
    CanonicalSemanticEvent,
    CanonicalSemanticGroup,
    CanonicalVisualLocator,
    CanonicalVisualProgression,
    CompoundVisualClassification,
    ContinuityMode,
    SemanticGroupAnimationPolicy,
    VisualFocus,
)
from app.models import SceneSource


def canonical_package(
    *,
    root: Path,
    package_id: str,
    scenes: list[SceneSource] | tuple[SceneSource, ...],
    script: str | None = None,
    semantics: dict[str, Any] | None = None,
    authoritative_semantics: bool | None = None,
    **_ignored: Any,
) -> CanonicalPackage:
    """Build an in-memory CanonicalPackage for layer tests.

    Production Final Package parsing is intentionally not emulated here. Tests that
    exercise the package boundary must use package.json through FinalPackageLoader.
    """

    semantic_scenes = {
        str(row.get("scene_id")): row
        for row in (semantics or {}).get("scenes", [])
        if isinstance(row, Mapping) and row.get("scene_id")
    }
    output: list[CanonicalScene] = []
    for source in scenes:
        sem = semantic_scenes.get(source.id, {})
        structural_units = [row for row in source.units if isinstance(row, Mapping)]
        semantic_assets = {
            str(row.get("asset_id")): row
            for row in sem.get("assets", [])
            if isinstance(row, Mapping) and row.get("asset_id")
        }
        structural_by_id = {
            str(row.get("asset_id") or row.get("unit_id")): row
            for row in structural_units
            if row.get("asset_id") or row.get("unit_id")
        }
        asset_ids = list(dict.fromkeys([*structural_by_id, *semantic_assets]))
        units = [
            _asset(source.id, structural_by_id.get(asset_id, {}), semantic_assets.get(asset_id, {}))
            for asset_id in asset_ids
        ]
        for index, row in enumerate(structural_units, start=1):
            if row.get("asset_id") or row.get("unit_id"):
                continue
            fallback = dict(row)
            fallback_id = f"{source.id}:unit-{index:03d}"
            fallback.setdefault("unit_id", fallback_id)
            fallback.setdefault("asset_id", fallback_id)
            fallback.setdefault("type", "LEGACY_UNIT")
            units.append(_asset(source.id, fallback, {}))

        event_rows = sem.get("semantic_events") or source.semantic_events or []
        relation_rows = sem.get("relations") or []
        group_rows = sem.get("semantic_groups") or []
        progression = sem.get("progression") or source.semantic_progression
        visual_progression = source.visual_progression or []

        output.append(CanonicalScene(
            id=source.id,
            image_path=source.image_path,
            order=source.order,
            title=source.title,
            narration_hint=source.narration_hint,
            script_char_start=source.script_char_start,
            script_char_end=source.script_char_end,
            purpose=source.purpose,
            visual_concept=source.visual_concept,
            relation_to_previous=source.relation_to_previous,
            character_category=_string(sem.get("character_category")),
            units=tuple(units),
            visual_progression=tuple(_visual_progression(row) for row in visual_progression if isinstance(row, Mapping)),
            semantic_events=tuple(_event(row, source.id) for row in event_rows if isinstance(row, Mapping)),
            semantic_groups=tuple(_group(row) for row in group_rows if isinstance(row, Mapping)),
            relations=tuple(_relation(row) for row in relation_rows if isinstance(row, Mapping)),
            semantic_progression=_progression(progression) if isinstance(progression, Mapping) else None,
        ))
    if authoritative_semantics is None:
        authoritative_semantics = bool(semantics)
    return CanonicalPackage(
        root=root,
        package_id=package_id,
        script=script,
        scenes=tuple(output),
        has_authoritative_semantics=bool(authoritative_semantics),
    )


def _asset(scene_id: str, structural: Mapping[str, Any], semantic: Mapping[str, Any]) -> CanonicalAsset:
    row = dict(structural)
    row.update(semantic)
    asset_id = _string(row.get("asset_id") or row.get("unit_id"))
    if asset_id is None:
        raise ValueError(f"asset identity required: {scene_id}")
    return CanonicalAsset(
        unit_id=_string(row.get("unit_id")) or asset_id,
        asset_id=asset_id,
        scene_id=scene_id,
        type=_string(row.get("type")) or "VISUAL_ASSET_INTENT",
        referent_id=_string(row.get("referent_id")),
        semantic_name=_string(row.get("semantic_name")),
        visual_concept=_string(row.get("visual_concept")),
        semantic_meaning=_string(row.get("semantic_meaning")),
        role=_string(row.get("role")),
        semantic_role=_string(row.get("semantic_role")),
        semantic_intent=_string(row.get("semantic_intent")),
        narrative_function=_string(row.get("narrative_function")),
        binding_type=_enum(BindingType, row.get("binding_type")),
        script_text=_string(row.get("script_text")),
        script_span=_span(row.get("script_span")),
        appear_trigger=_span(row.get("appear_trigger")),
        focus_trigger=_span(row.get("focus_trigger")),
        exit_trigger=_span(row.get("exit_trigger")),
        semantic_group_id=_string(row.get("semantic_group_id")),
        sequence_order=_int(row.get("sequence_order")),
        parent_asset_id=_string(row.get("parent_asset_id")),
        children_asset_ids=_strings(row.get("children_asset_ids")),
        confidence=_float(row.get("confidence"), 1.0),
        interaction_target=_string(row.get("interaction_target")),
        relationship=_string(row.get("relationship")),
        semantic_event_id=_string(row.get("semantic_event_id")),
        anchor_granularity=_enum(AnchorGranularity, row.get("anchor_granularity")),
        visual_focus=_enum(VisualFocus, row.get("visual_focus")),
        visual_state=dict(row["visual_state"]) if isinstance(row.get("visual_state"), Mapping) else None,
        continuity=_continuity(row.get("continuity")),
        compound_visual_classification=_enum(CompoundVisualClassification, row.get("compound_visual_classification")),
        internal_progression_unavailable=bool(row.get("internal_progression_unavailable", False)),
        needs_review=bool(row.get("needs_review", False)),
        ambiguity_reason=_string(row.get("ambiguity_reason")),
        visual_locator=_locator(row.get("visual_locator")),
    )


def _event(row: Mapping[str, Any], scene_id: str) -> CanonicalSemanticEvent:
    return CanonicalSemanticEvent(
        semantic_event_id=str(row["semantic_event_id"]),
        scene_id=_string(row.get("scene_id")) or scene_id,
        script_text=_string(row.get("script_text")),
        script_span=_span(row.get("script_span")),
        anchor_granularity=_enum(AnchorGranularity, row.get("anchor_granularity")),
        sequence_order=_int(row.get("sequence_order")),
        visual_leader_asset_id=_string(row.get("visual_leader_asset_id")),
        participant_asset_ids=_strings(row.get("participant_asset_ids")),
        context_asset_ids=_strings(row.get("context_asset_ids")),
        result_asset_ids=_strings(row.get("result_asset_ids")),
        text_anchor_asset_id=_string(row.get("text_anchor_asset_id")),
        confidence=_float(row.get("confidence"), 1.0),
        needs_review=bool(row.get("needs_review", False)),
        ambiguity_reason=_string(row.get("ambiguity_reason")),
        depends_on_event_ids=_strings(row.get("depends_on_event_ids")),
    )


def _group(row: Mapping[str, Any]) -> CanonicalSemanticGroup:
    return CanonicalSemanticGroup(
        semantic_group_id=str(row["semantic_group_id"]),
        script_text=_string(row.get("script_text")),
        animation_policy=_enum(SemanticGroupAnimationPolicy, row.get("animation_policy")) or SemanticGroupAnimationPolicy.SEQUENTIAL_WITHIN_PHRASE,
        asset_ids=_strings(row.get("asset_ids")),
    )


def _relation(row: Mapping[str, Any]) -> CanonicalRelation:
    return CanonicalRelation(
        subject_asset_id=str(row["subject_asset_id"]),
        relation_type=str(row.get("relation_type") or row.get("relationship")),
        object_asset_id=str(row["object_asset_id"]),
        result_asset_id=_string(row.get("result_asset_id")),
        script_text=_string(row.get("script_text")),
        script_span=_span(row.get("script_span")),
        confidence=_float(row.get("confidence"), 1.0),
    )


def _progression(row: Mapping[str, Any]) -> CanonicalProgression:
    return CanonicalProgression(type=_string(row.get("type")), event_order=_strings(row.get("event_order")))


def _visual_progression(row: Mapping[str, Any]) -> CanonicalVisualProgression:
    return CanonicalVisualProgression(
        action=_string(row.get("action")) or "EXPLAIN",
        targets=_strings(row.get("targets")),
        trigger=_span(row.get("trigger")),
    )


def _continuity(value: Any) -> CanonicalContinuity | None:
    if not isinstance(value, Mapping):
        return None
    mode = _enum(ContinuityMode, value.get("mode"))
    target = _string(value.get("target_asset_id"))
    if mode is None and target is None:
        return None
    return CanonicalContinuity(mode=mode, target_asset_id=target)


def _span(value: Any) -> CanonicalScriptSpan | None:
    if not isinstance(value, Mapping):
        return None
    text = _string(value.get("text") or value.get("phrase"))
    start = _int(value.get("global_char_start") if value.get("global_char_start") is not None else value.get("char_start"))
    end = _int(value.get("global_char_end") if value.get("global_char_end") is not None else value.get("char_end"))
    if text is None and start is None and end is None:
        return None
    return CanonicalScriptSpan(text=text, global_char_start=start, global_char_end=end)


def _locator(value: Any) -> CanonicalVisualLocator | None:
    if not isinstance(value, Mapping) or value.get("cx") is None:
        return None
    return CanonicalVisualLocator(
        coordinate_space=str(value.get("coordinate_space") or "normalized_scene"),
        cx=float(value["cx"]), cy=float(value["cy"]), width=float(value["width"]), height=float(value["height"]),
    )


def _enum(enum_type, value):
    text = _string(value)
    return enum_type(text.upper()) if text is not None else None


def _string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _strings(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(str(item) for item in value if item is not None and str(item).strip())


def _int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    return int(value)


def _float(value: Any, default: float) -> float:
    if value is None or isinstance(value, bool):
        return default
    return float(value)
