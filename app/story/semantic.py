from __future__ import annotations

import re
from collections.abc import Iterable

from app.canonical import (
    CanonicalAsset,
    CanonicalContinuity,
    CanonicalProgression,
    CanonicalRelation,
    CanonicalScene,
    CanonicalScriptSpan,
    CanonicalVisualProgression,
)
from app.models import (
    StoryEntity,
    StoryRelation,
    StorySemanticContext,
    StoryTrigger,
)


# Canonical fields held at Final Package / Canonical authority only until a runtime layer
# explicitly consumes them. Copying them into Story metadata would change serialized
# plans without any consumer (Sprint 7A: authored referent identity stays dormant).
_DORMANT_CANONICAL_FIELDS = frozenset({"referent_id"})


class PackageStoryInterpreter:
    """Compile Final Package metadata into conservative story semantics.

    The Final Package is the semantic authority. This interpreter never invents
    entities or relationships that are absent from the package. It may classify
    explicit semantic evidence into a small generic story-role vocabulary so later
    authoring layers do not need project/topic-specific rules.
    """

    _RESOLUTION = frozenset(
        {
            "resolve",
            "resolution",
            "solution",
            "remedy",
            "fix",
            "alternate",
            "alternative",
            "recover",
            "restore",
            "review",
            "raise",
            "reduce",
            "adjust",
        }
    )
    _CONSEQUENCE = frozenset(
        {
            "result",
            "consequence",
            "reaction",
            "react",
            "reject",
            "rejected",
            "decline",
            "declined",
            "fail",
            "failed",
            "success",
            "accept",
            "accepted",
            "blocked",
        }
    )
    _COMPLICATION = frozenset(
        {
            "conflict",
            "constraint",
            "restriction",
            "problem",
            "insufficient",
            "limit",
            "cap",
            "exceed",
            "reserved",
            "reserve",
            "hold",
            "locked",
            "unavailable",
            "block",
        }
    )
    _ACTION = frozenset(
        {
            "action",
            "attempt",
            "request",
            "transfer",
            "send",
            "route",
            "reach",
            "process",
            "retry",
            "change",
            "move",
            "scan",
        }
    )
    _COMPARISON = frozenset(
        {"compare", "comparison", "contrast", "difference", "versus", "parallel", "separate"}
    )
    _RESULT_HINTS = frozenset(
        {
            "result",
            "reaction",
            "status",
            "outcome",
            "reject",
            "decline",
            "accept",
            "success",
            "fail",
            "blocked",
            "resolve",
        }
    )
    _CAUSAL_RELATION_HINTS = frozenset(
        {
            "causes",
            "blocks",
            "rejects",
            "accepts",
            "transfers",
            "sends",
            "receives",
            "produces",
            "results_in",
            "reacts_to",
            "depends_on",
            "triggers",
            "attacks",
            "grants_access_to",
            "creates",
            "repairs",
            "reports_to",
            "authorizes",
            "depends_on",
            "enables",
            "causes",
            "causes_unused_security",
            "leads_to",
            "leads_to_discovery",
            "reveals_identity",
            "parallel_causes",
            "withholds_disclosure",
            "progresses_to",
            "persists_over_time",
            "contains_risk",
        }
    )

    def interpret(
        self,
        scene: CanonicalScene,
        event: CanonicalVisualProgression,
        *,
        is_first_beat: bool,
        default_event: bool = False,
    ) -> StorySemanticContext:
        target_ids = tuple(str(value) for value in event.targets if value)
        units_by_id = {unit.unit_id: unit for unit in scene.units if unit.unit_id}

        relevant_units = self._relevant_units(scene.units, target_ids)
        entities = [self._entity(unit) for unit in relevant_units if unit.unit_id]
        entity_by_id = {entity.unit_id: entity for entity in entities}

        binding_assets = list(scene.assets)
        binding_assets_by_id = {row.asset_id: row for row in binding_assets}
        semantic_events = list(scene.semantic_events)
        for asset in binding_assets:
            unit_id = asset.asset_id
            entity_by_id[unit_id] = self._entity(asset)
        entities = list(entity_by_id.values())
        entity_ids = set(entity_by_id)

        relations: list[StoryRelation] = []
        for relation in scene.relations:
            source = relation.subject_asset_id
            target = relation.object_asset_id
            relationship = relation.relation_type.strip()
            if not source or not target or not relationship:
                continue
            span = relation.script_span or self._relation_span_from_assets(
                relation,
                binding_assets_by_id,
            )
            relations.append(
                StoryRelation(
                    source_unit_id=source,
                    target_unit_id=target,
                    result_unit_id=self._string_or_none(relation.result_asset_id),
                    kind=relationship,
                    authority="FINAL_PACKAGE_ASSET_RELATION",
                    trigger_text=self._string_or_none(relation.script_text),
                    trigger_char_start=(span.global_char_start if span is not None else None),
                    trigger_char_end=(span.global_char_end if span is not None else None),
                    confidence=float(relation.confidence),
                    causal=self._is_causal_relation(relationship),
                )
            )

        for unit in relevant_units:
            source = unit.unit_id
            target = str(unit.interaction_target or "")
            relationship = str(unit.relationship or "").strip()
            if not source or not target or target not in units_by_id or not relationship:
                continue
            relations.append(
                StoryRelation(
                    source_unit_id=source,
                    target_unit_id=target,
                    kind=relationship,
                    authority="FINAL_PACKAGE_INTERACTION_TARGET",
                    confidence=1.0,
                    causal=self._is_causal_relation(relationship),
                )
            )

        # Declared progression carries ordering authority but is not silently upgraded
        # to a causal claim. The event may contain multiple targets that are intended to
        # be revealed/read in sequence.
        for source, target in zip(target_ids, target_ids[1:]):
            if source in entity_ids and target in entity_ids:
                relations.append(
                    StoryRelation(
                        source_unit_id=source,
                        target_unit_id=target,
                        kind="DECLARED_PROGRESSION",
                        authority="FINAL_PACKAGE_VISUAL_PROGRESSION",
                        confidence=0.96,
                        causal=False,
                    )
                )

        explicit_authorities = {
            "FINAL_PACKAGE_ASSET_RELATION",
            "FINAL_PACKAGE_INTERACTION_TARGET",
        }
        subject_ids = self._unique(
            relation.source_unit_id
            for relation in relations
            if relation.authority in explicit_authorities
        )
        if not subject_ids:
            subject_ids = self._unique(
                entity.unit_id for entity in entities if self._normalize(entity.role) == "primary"
            )

        object_ids = self._unique(
            relation.target_unit_id
            for relation in relations
            if relation.authority in explicit_authorities
        )
        explicit_reaction_sources = {
            relation.source_unit_id
            for relation in relations
            if self._normalize(relation.kind) in {"reacts_to", "reaction_to"}
        }
        explicit_result_ids = self._unique(
            relation.result_unit_id
            for relation in relations
            if relation.authority in explicit_authorities and relation.result_unit_id
        )
        inferred_result_ids = self._unique(
            entity.unit_id
            for entity in entities
            if (
                self._normalize(entity.role) == "primary"
                and self._contains_any(
                    " ".join(
                        filter(
                            None,
                            [
                                entity.semantic_name,
                                entity.narrative_function,
                                entity.semantic_intent,
                            ],
                        )
                    ),
                    self._RESULT_HINTS,
                )
            )
            or self._normalize(entity.semantic_intent) in {"reaction", "result"}
            or entity.unit_id in explicit_reaction_sources
        )
        event_result_ids = self._unique(
            asset_id
            for event_row in semantic_events
            for asset_id in event_row.result_asset_ids
            if asset_id
        )
        result_ids = self._unique([
            *explicit_result_ids,
            *event_result_ids,
            *inferred_result_ids,
        ])

        event_leader_ids = self._unique(
            row.visual_leader_asset_id
            for row in semantic_events
            if row.visual_leader_asset_id
        )
        focus_unit_ids = (
            event_leader_ids
            if event_leader_ids
            else self._unique(
                row.asset_id
                for row in binding_assets
                if row.visual_focus is not None
            )
        )
        visual_states = {
            row.asset_id: {
                "before": str(row.visual_state["before"]),
                "after": str(row.visual_state["after"]),
            }
            for row in binding_assets
            if row.visual_state
            and row.visual_state.get("before")
            and row.visual_state.get("after")
        }
        continuity_by_unit = {
            row.asset_id: self._continuity_metadata(row.continuity)
            for row in binding_assets
            if row.continuity is not None
        }

        narrative_functions = self._unique(
            entity.narrative_function for entity in entities if entity.narrative_function
        )
        semantic_intents = self._unique(
            entity.semantic_intent for entity in entities if entity.semantic_intent
        )

        # Story role follows the event and primary semantic subject. Supporting actors
        # frequently advertise generic capabilities such as "context or reaction"; those
        # must not turn an otherwise explanatory beat into a consequence unless the
        # package explicitly marks a reaction relationship/intent.
        primary_entities = [
            entity for entity in entities if self._normalize(entity.role) == "primary"
        ] or entities[:1]
        corpus_parts: list[str] = [str(event.action or "")]
        for entity in primary_entities:
            corpus_parts.extend(
                value
                for value in (
                    entity.semantic_name,
                    entity.narrative_function,
                    entity.semantic_intent,
                    entity.entity_type,
                )
                if value
            )
        for relation in relations:
            if relation.causal or self._normalize(relation.kind) in {"reacts_to", "reaction_to"}:
                corpus_parts.append(relation.kind)
        for entity in entities:
            if self._normalize(entity.semantic_intent) in {"reaction", "result"}:
                corpus_parts.append(entity.semantic_intent or "")
        role_corpus = " ".join(corpus_parts)
        latent_role = self._story_role(role_corpus, is_first_beat=False)
        story_role = "SETUP" if is_first_beat else latent_role
        tension = self._tension_for(latent_role if is_first_beat else story_role)
        evidence = self._evidence(
            scene, event, entities, relations, default_event=default_event
        )
        if scene.assets or scene.semantic_events or scene.relations:
            evidence.append("final_package_asset_level_semantics")
            if relations:
                evidence.append("final_package_asset_relations")
            if semantic_events:
                evidence.append("final_package_semantic_events")
                if scene.semantic_progression is not None:
                    evidence.append("final_package_event_progression")
            if focus_unit_ids:
                evidence.append(
                    "final_package_event_leaders"
                    if event_leader_ids
                    else "final_package_visual_focus"
                )
            if visual_states:
                evidence.append("final_package_visual_state")
        confidence = self._confidence(scene, entities, relations, target_ids)

        return StorySemanticContext(
            story_role=story_role,
            event_id=None,
            event_order=None,
            event_trigger=self._trigger(
                event.trigger, phrase_from_text=default_event
            ),
            scene_purpose=scene.purpose,
            scene_visual_concept=scene.visual_concept,
            scene_metadata={
                "purpose": scene.purpose,
                "visual_concept": scene.visual_concept,
                "relation_to_previous": scene.relation_to_previous,
                "script_char_start": scene.script_char_start,
                "script_char_end": scene.script_char_end,
                "semantic_event_count": len(semantic_events),
                "semantic_progression": self._progression_metadata(scene.semantic_progression),
            },
            event_metadata=self._event_metadata(event, default_event=default_event),
            entities=entities,
            relations=relations,
            subject_unit_ids=subject_ids,
            object_unit_ids=object_ids,
            result_unit_ids=result_ids,
            focus_unit_ids=focus_unit_ids,
            visual_states=visual_states,
            continuity_by_unit=continuity_by_unit,
            narrative_functions=narrative_functions,
            semantic_intents=semantic_intents,
            continuity_relation=scene.relation_to_previous,
            evidence=evidence,
            confidence=confidence,
            tension=tension,
        )

    @staticmethod
    def _relevant_units(
        units: tuple[CanonicalAsset, ...],
        target_ids: tuple[str, ...],
    ) -> list[CanonicalAsset]:
        rows = list(units)
        if not target_ids:
            return rows
        selected = [unit for unit in rows if unit.unit_id in target_ids]
        selected_ids = {unit.unit_id for unit in selected}
        relation_targets = {
            str(unit.interaction_target)
            for unit in selected
            if unit.interaction_target
        }
        for unit in rows:
            if unit.unit_id in relation_targets and unit.unit_id not in selected_ids:
                selected.append(unit)
                selected_ids.add(unit.unit_id)
        return selected or rows

    @staticmethod
    def _entity(unit: CanonicalAsset) -> StoryEntity:
        semantic_name = (
            unit.semantic_meaning
            or unit.semantic_name
            or unit.visual_concept
            or unit.unit_id
        )
        role = unit.semantic_role or unit.role
        metadata = PackageStoryInterpreter._record_metadata(unit)
        # Preserve the proven pre-refactor Story metadata contract: semantic bindings
        # overrode the scene-plan display name/role in the merged runtime entity view.
        metadata["semantic_name"] = semantic_name
        metadata["role"] = role
        return StoryEntity(
            unit_id=unit.unit_id,
            semantic_name=PackageStoryInterpreter._string_or_none(semantic_name),
            entity_type=PackageStoryInterpreter._string_or_none(unit.type),
            role=PackageStoryInterpreter._string_or_none(role),
            narrative_function=PackageStoryInterpreter._string_or_none(unit.narrative_function),
            semantic_intent=PackageStoryInterpreter._string_or_none(unit.semantic_intent),
            # CanonicalScriptSpan stores the normalized phrase in ``text``. The old
            # Mapping bridge did not expose that as ``phrase`` for asset triggers, so
            # preserve that exact behavior while retaining the authored char anchors.
            appear_trigger=PackageStoryInterpreter._trigger(unit.appear_trigger),
            focus_trigger=PackageStoryInterpreter._trigger(unit.focus_trigger),
            exit_trigger=PackageStoryInterpreter._trigger(unit.exit_trigger),
            package_metadata=metadata,
        )

    @staticmethod
    def _trigger(
        value: CanonicalScriptSpan | None,
        *,
        phrase_from_text: bool = False,
    ) -> StoryTrigger | None:
        if value is None:
            return None
        return StoryTrigger(
            phrase=(
                PackageStoryInterpreter._string_or_none(value.text)
                if phrase_from_text
                else None
            ),
            occurrence_in_scene=None,
            global_char_start=value.global_char_start,
            global_char_end=value.global_char_end,
        )

    def _story_role(self, value: str, *, is_first_beat: bool) -> str:
        normalized = self._normalize(value)
        tokens = set(normalized.split("_"))
        if is_first_beat:
            return "SETUP"
        if tokens & self._RESOLUTION:
            return "RESOLUTION"
        if tokens & self._CONSEQUENCE:
            return "CONSEQUENCE"
        if tokens & self._COMPLICATION:
            return "COMPLICATION"
        if tokens & self._COMPARISON:
            return "COMPARISON"
        if tokens & self._ACTION:
            return "ACTION"
        return "CONTEXT"

    @classmethod
    def _is_causal_relation(cls, relationship: str) -> bool:
        normalized = cls._normalize(relationship)
        return normalized in cls._CAUSAL_RELATION_HINTS or any(
            hint in normalized for hint in cls._CAUSAL_RELATION_HINTS
        )

    @staticmethod
    def _tension_for(story_role: str) -> float:
        return {
            "SETUP": 0.22,
            "CONTEXT": 0.30,
            "COMPARISON": 0.46,
            "ACTION": 0.56,
            "COMPLICATION": 0.74,
            "CONSEQUENCE": 0.80,
            "RESOLUTION": 0.38,
        }.get(story_role, 0.30)

    @staticmethod
    def _confidence(
        scene: CanonicalScene,
        entities: list[StoryEntity],
        relations: list[StoryRelation],
        target_ids: tuple[str, ...],
    ) -> float:
        if not entities:
            return 0.35
        explicit_fields = 0
        total_fields = 0
        for entity in entities:
            for value in (
                entity.semantic_name,
                entity.entity_type,
                entity.role,
                entity.narrative_function,
                entity.semantic_intent,
            ):
                total_fields += 1
                explicit_fields += int(bool(value))
        field_coverage = explicit_fields / max(1, total_fields)
        score = 0.46 + field_coverage * 0.34
        if target_ids:
            score += 0.08
        if relations:
            score += 0.07
        if scene.visual_concept or scene.purpose:
            score += 0.05
        return round(min(1.0, score), 3)

    @staticmethod
    def _evidence(
        scene: CanonicalScene,
        event: CanonicalVisualProgression,
        entities: list[StoryEntity],
        relations: list[StoryRelation],
        *,
        default_event: bool = False,
    ) -> list[str]:
        output: list[str] = []
        if event.action:
            output.append(f"event_action:{event.action}")
        if scene.relation_to_previous:
            output.append(f"scene_relation:{scene.relation_to_previous}")
        if scene.visual_concept:
            output.append(f"scene_visual_concept:{scene.visual_concept}")
        if scene.purpose:
            output.append(f"scene_purpose:{scene.purpose}")
        trigger = event.trigger
        if trigger is not None:
            if default_event and trigger.text:
                output.append(f"event_trigger_phrase:{trigger.text}")
            if (
                trigger.global_char_start is not None
                or trigger.global_char_end is not None
            ):
                output.append(
                    f"event_trigger_chars:{trigger.global_char_start}:{trigger.global_char_end}"
                )
        for entity in entities:
            if entity.semantic_name:
                output.append(f"entity:{entity.unit_id}:{entity.semantic_name}")
            if entity.entity_type:
                output.append(f"entity_type:{entity.unit_id}:{entity.entity_type}")
            if entity.role:
                output.append(f"entity_role:{entity.unit_id}:{entity.role}")
            if entity.narrative_function:
                output.append(
                    f"entity_narrative_function:{entity.unit_id}:{entity.narrative_function}"
                )
            if entity.semantic_intent:
                output.append(f"entity_semantic_intent:{entity.unit_id}:{entity.semantic_intent}")
            for name, unit_trigger in (
                ("appear", entity.appear_trigger),
                ("focus", entity.focus_trigger),
                ("exit", entity.exit_trigger),
            ):
                if unit_trigger is None:
                    continue
                if unit_trigger.phrase:
                    output.append(
                        f"entity_{name}_phrase:{entity.unit_id}:{unit_trigger.phrase}"
                    )
                if (
                    unit_trigger.global_char_start is not None
                    or unit_trigger.global_char_end is not None
                ):
                    output.append(
                        f"entity_{name}_chars:{entity.unit_id}:"
                        f"{unit_trigger.global_char_start}:{unit_trigger.global_char_end}"
                    )
        output.extend(
            f"relation:{relation.source_unit_id}:{relation.kind}:{relation.target_unit_id}"
            for relation in relations
        )
        return PackageStoryInterpreter._unique(output)

    @classmethod
    def _relation_span_from_assets(
        cls,
        relation: CanonicalRelation,
        assets_by_id: dict[str, CanonicalAsset],
    ) -> CanonicalScriptSpan | None:
        """Derive relation timing only from authored participant spans."""
        participant_ids = (
            relation.subject_asset_id,
            relation.object_asset_id,
            relation.result_asset_id,
        )
        spans: list[tuple[int, int]] = []
        required = 0
        resolved_required = 0
        for index, asset_id in enumerate(participant_ids):
            if not asset_id:
                continue
            if index < 2:
                required += 1
            asset = assets_by_id.get(str(asset_id))
            asset_span = asset.script_span if asset is not None else None
            if asset_span is None:
                continue
            start = asset_span.global_char_start
            end = asset_span.global_char_end
            if start is None or end is None or end <= start:
                continue
            spans.append((start, end))
            if index < 2:
                resolved_required += 1
        if required < 2 or resolved_required < required or not spans:
            return None
        return CanonicalScriptSpan(
            global_char_start=min(start for start, _end in spans),
            global_char_end=max(end for _start, end in spans),
        )

    @staticmethod
    def _event_metadata(
        event: CanonicalVisualProgression,
        *,
        default_event: bool,
    ) -> dict:
        if default_event:
            trigger = event.trigger
            return {
                "action": event.action,
                "targets": list(event.targets),
                "trigger": (
                    {
                        "global_char_start": trigger.global_char_start,
                        "global_char_end": trigger.global_char_end,
                        "phrase": trigger.text,
                    }
                    if trigger is not None
                    else None
                ),
            }
        return PackageStoryInterpreter._record_metadata(event)

    @staticmethod
    def _record_metadata(record) -> dict:
        return {
            name: getattr(record, name)
            for name in type(record).model_fields
            if name not in _DORMANT_CANONICAL_FIELDS
        }

    @staticmethod
    def _progression_metadata(value: CanonicalProgression | None):
        if value is None:
            return None
        return PackageStoryInterpreter._record_metadata(value)

    @staticmethod
    def _continuity_metadata(value: CanonicalContinuity | None) -> dict:
        if value is None:
            return {}
        return {
            "mode": value.mode,
            "target_asset_id": value.target_asset_id,
            **dict(value.extension_metadata),
        }

    @classmethod
    def _contains_any(cls, value: str, needles: frozenset[str]) -> bool:
        tokens = set(cls._normalize(value).split("_"))
        return bool(tokens & needles)

    @staticmethod
    def _normalize(value: str | None) -> str:
        text = str(value or "").casefold().replace("-", "_").replace("/", "_")
        return re.sub(r"[^\w\u0600-\u06ff]+", "_", text).strip("_")

    @staticmethod
    def _int_or_none(value) -> int | None:
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _string_or_none(value) -> str | None:
        text = str(value or "").strip()
        return text or None

    @staticmethod
    def _unique(values: Iterable[str | None]) -> list[str]:
        output: list[str] = []
        seen: set[str] = set()
        for value in values:
            if not value:
                continue
            text = str(value)
            if text in seen:
                continue
            seen.add(text)
            output.append(text)
        return output
