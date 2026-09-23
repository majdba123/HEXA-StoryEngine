from __future__ import annotations

import re
from collections.abc import Iterable

from app.models import (
    SceneSource,
    StoryEntity,
    StoryRelation,
    StorySemanticContext,
    StoryTrigger,
)


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
        }
    )

    def interpret(
        self,
        scene: SceneSource,
        event: dict,
        *,
        is_first_beat: bool,
        semantic_binding_scene: dict | None = None,
    ) -> StorySemanticContext:
        target_ids = tuple(str(value) for value in event.get("targets", []) if value)
        units_by_id = {
            str(unit.get("unit_id")): unit
            for unit in scene.units
            if isinstance(unit, dict) and unit.get("unit_id")
        }

        relevant_units = self._relevant_units(scene.units, target_ids)
        entities = [self._entity(unit) for unit in relevant_units if unit.get("unit_id")]
        entity_by_id = {entity.unit_id: entity for entity in entities}

        binding_assets = [
            row
            for row in (semantic_binding_scene or {}).get("assets", [])
            if isinstance(row, dict) and row.get("asset_id")
        ]
        for asset in binding_assets:
            unit_id = str(asset.get("asset_id"))
            scene_unit = units_by_id.get(unit_id, {})
            merged = {**scene_unit, **asset, "unit_id": unit_id}
            merged["semantic_name"] = (
                asset.get("semantic_meaning")
                or scene_unit.get("semantic_name")
                or asset.get("visual_concept")
                or unit_id
            )
            merged["role"] = (
                asset.get("semantic_role")
                or asset.get("role")
                or scene_unit.get("role")
            )
            entity_by_id[unit_id] = self._entity(merged)
        entities = list(entity_by_id.values())
        entity_ids = set(entity_by_id)

        relations: list[StoryRelation] = []
        for relation in (semantic_binding_scene or {}).get("relations", []) or []:
            if not isinstance(relation, dict):
                continue
            source = str(relation.get("subject_asset_id") or "")
            target = str(relation.get("object_asset_id") or "")
            relationship = str(relation.get("relationship") or "").strip()
            if not source or not target or not relationship:
                continue
            span = relation.get("script_span")
            relations.append(
                StoryRelation(
                    source_unit_id=source,
                    target_unit_id=target,
                    result_unit_id=self._string_or_none(relation.get("result_asset_id")),
                    kind=relationship,
                    authority="FINAL_PACKAGE_ASSET_RELATION",
                    trigger_text=self._string_or_none(relation.get("script_text")),
                    trigger_char_start=(
                        self._int_or_none(span.get("char_start"))
                        if isinstance(span, dict)
                        else None
                    ),
                    trigger_char_end=(
                        self._int_or_none(span.get("char_end"))
                        if isinstance(span, dict)
                        else None
                    ),
                    confidence=float(relation.get("confidence", 1.0)),
                    causal=self._is_causal_relation(relationship),
                )
            )

        for unit in relevant_units:
            source = str(unit.get("unit_id") or "")
            target = str(unit.get("interaction_target") or "")
            relationship = str(unit.get("relationship") or "").strip()
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
        result_ids = self._unique([*explicit_result_ids, *inferred_result_ids])

        focus_unit_ids = self._unique(
            str(row.get("asset_id"))
            for row in binding_assets
            if row.get("visual_focus")
        )
        visual_states = {
            str(row.get("asset_id")): {
                "before": str(row["visual_state"]["before"]),
                "after": str(row["visual_state"]["after"]),
            }
            for row in binding_assets
            if isinstance(row.get("visual_state"), dict)
            and row["visual_state"].get("before")
            and row["visual_state"].get("after")
        }
        continuity_by_unit = {
            str(row.get("asset_id")): dict(row["continuity"])
            for row in binding_assets
            if isinstance(row.get("continuity"), dict)
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
        corpus_parts: list[str] = [str(event.get("action") or "")]
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
        # Opening beats still preserve the semantic pressure of the problem they set up.
        # This lets the retention layer recognize a high-tension opener without changing
        # the structural arc role from SETUP.
        tension = self._tension_for(latent_role if is_first_beat else story_role)
        evidence = self._evidence(scene, event, entities, relations)
        if semantic_binding_scene is not None:
            evidence.append("final_package_asset_level_semantics")
            if relations:
                evidence.append("final_package_asset_relations")
            if focus_unit_ids:
                evidence.append("final_package_visual_focus")
            if visual_states:
                evidence.append("final_package_visual_state")
        confidence = self._confidence(scene, entities, relations, target_ids)

        return StorySemanticContext(
            story_role=story_role,
            event_id=self._string_or_none(event.get("event_id")),
            event_order=self._int_or_none(event.get("order")),
            event_trigger=self._trigger(event.get("trigger")),
            scene_purpose=scene.purpose,
            scene_visual_concept=scene.visual_concept,
            scene_metadata={
                "purpose": scene.purpose,
                "visual_concept": scene.visual_concept,
                "relation_to_previous": scene.relation_to_previous,
                "script_char_start": scene.script_char_start,
                "script_char_end": scene.script_char_end,
            },
            event_metadata=dict(event),
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
    def _relevant_units(units: list[dict], target_ids: tuple[str, ...]) -> list[dict]:
        rows = [unit for unit in units if isinstance(unit, dict)]
        if not target_ids:
            return rows
        selected = [unit for unit in rows if str(unit.get("unit_id") or "") in target_ids]
        # Include explicit relation endpoints even if visual_progression omitted them.
        selected_ids = {str(unit.get("unit_id") or "") for unit in selected}
        relation_targets = {
            str(unit.get("interaction_target"))
            for unit in selected
            if unit.get("interaction_target")
        }
        for unit in rows:
            unit_id = str(unit.get("unit_id") or "")
            if unit_id in relation_targets and unit_id not in selected_ids:
                selected.append(unit)
                selected_ids.add(unit_id)
        return selected or rows

    @staticmethod
    def _entity(unit: dict) -> StoryEntity:
        return StoryEntity(
            unit_id=str(unit.get("unit_id")),
            semantic_name=PackageStoryInterpreter._string_or_none(unit.get("semantic_name")),
            entity_type=PackageStoryInterpreter._string_or_none(unit.get("type")),
            role=PackageStoryInterpreter._string_or_none(unit.get("role")),
            narrative_function=PackageStoryInterpreter._string_or_none(unit.get("narrative_function")),
            semantic_intent=PackageStoryInterpreter._string_or_none(unit.get("semantic_intent")),
            appear_trigger=PackageStoryInterpreter._trigger(unit.get("appear_trigger")),
            focus_trigger=PackageStoryInterpreter._trigger(unit.get("focus_trigger")),
            exit_trigger=PackageStoryInterpreter._trigger(unit.get("exit_trigger")),
            package_metadata=dict(unit),
        )

    @staticmethod
    def _trigger(value) -> StoryTrigger | None:
        if not isinstance(value, dict):
            return None
        return StoryTrigger(
            phrase=PackageStoryInterpreter._string_or_none(value.get("phrase")),
            occurrence_in_scene=PackageStoryInterpreter._int_or_none(value.get("occurrence_in_scene")),
            global_char_start=PackageStoryInterpreter._int_or_none(value.get("global_char_start")),
            global_char_end=PackageStoryInterpreter._int_or_none(value.get("global_char_end")),
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
        scene: SceneSource,
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
        scene: SceneSource,
        event: dict,
        entities: list[StoryEntity],
        relations: list[StoryRelation],
    ) -> list[str]:
        output: list[str] = []
        if event.get("action"):
            output.append(f"event_action:{event['action']}")
        if scene.relation_to_previous:
            output.append(f"scene_relation:{scene.relation_to_previous}")
        if scene.visual_concept:
            output.append(f"scene_visual_concept:{scene.visual_concept}")
        if scene.purpose:
            output.append(f"scene_purpose:{scene.purpose}")
        if event.get("event_id"):
            output.append(f"event_id:{event['event_id']}")
        if event.get("order") is not None:
            output.append(f"event_order:{event['order']}")
        trigger = event.get("trigger") if isinstance(event.get("trigger"), dict) else {}
        if trigger.get("phrase"):
            output.append(f"event_trigger_phrase:{trigger['phrase']}")
        if trigger.get("global_char_start") is not None or trigger.get("global_char_end") is not None:
            output.append(
                f"event_trigger_chars:{trigger.get('global_char_start')}:{trigger.get('global_char_end')}"
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
