from __future__ import annotations

from app.canonical import CanonicalScene
from app.models import StoryBeat, StoryEventAuthority, StorySemanticDiagnostic


def event_authority(
    scene: CanonicalScene, beat: StoryBeat
) -> tuple[list[StoryEventAuthority], list[StorySemanticDiagnostic]]:
    """Join authored events to Story's already proven visual carriers."""
    diagnostics: list[StorySemanticDiagnostic] = []
    records: list[StoryEventAuthority] = []
    authored_order = (
        tuple(scene.semantic_progression.event_order)
        if scene.semantic_progression is not None else ()
    )
    sequence_order = tuple(
        event.semantic_event_id
        for event in sorted(
            scene.semantic_events,
            key=lambda event: (event.sequence_order or 10**9, event.semantic_event_id),
        )
    )
    if authored_order and authored_order != sequence_order:
        diagnostics.append(StorySemanticDiagnostic(
            scene_id=scene.id, beat_id=beat.id,
            conflict_type="PROGRESSION_ORDER_CONFLICT",
            authority_sources=["FINAL_PACKAGE_SEMANTIC_PROGRESSION", "FINAL_PACKAGE_SEMANTIC_EVENT"],
            chosen_authority="FINAL_PACKAGE_SEMANTIC_EVENT.sequence_order",
        ))

    for unit in scene.assets:
        # CHARACTER/OBJECT/RESULT/ACTION describe meaning, while primary/supporting
        # describe presentation priority. They are not competing answers.
        if unit.priority_role_conflict:
            diagnostics.append(StorySemanticDiagnostic(
                scene_id=scene.id, beat_id=beat.id, asset_ids=[unit.asset_id],
                conflict_type="ROLE_CONFLICT",
                authority_sources=["FINAL_PACKAGE_ROLE", "FINAL_PACKAGE_SEMANTIC_ROLE"],
                chosen_authority="FINAL_PACKAGE_SEMANTIC_ROLE",
                fallback="CONTEXT_FOR_VISUAL_PROMOTION",
                source_values={"role": unit.role, "semantic_role": unit.semantic_role},
            ))
        if unit.needs_review or unit.ambiguity_reason or unit.confidence < 1.0:
            diagnostics.append(StorySemanticDiagnostic(
                scene_id=scene.id, beat_id=beat.id, asset_ids=[unit.asset_id],
                conflict_type=("ASSET_REVIEW" if unit.needs_review or unit.ambiguity_reason
                               else "ASSET_CONFIDENCE_PROVENANCE"),
                authority_sources=["FINAL_PACKAGE_ASSET"],
                chosen_authority="EXISTING_CARRIER_POLICY",
                source_values={"needs_review": unit.needs_review,
                               "ambiguity_reason": unit.ambiguity_reason,
                               "confidence": unit.confidence},
            ))

    explicit_results = {
        result_id for row in scene.semantic_events for result_id in row.result_asset_ids
    } | {relation.result_asset_id for relation in scene.relations if relation.result_asset_id}
    inferred_results = (
        set(beat.semantic_context.result_unit_ids) - explicit_results
        if beat.semantic_context is not None else set()
    )
    for event in scene.semantic_events:
        rows = [
            row for row in beat.asset_activations
            if row.semantic_event_id == event.semantic_event_id
            and row.policy != "SAFE_ABSTENTION"
            and getattr(row, "activation_policy", None) != "SAFE_ABSTENTION"
        ]
        rows.extend(
            proxy for proxy in beat.semantic_event_proxies
            if proxy.semantic_event_id == event.semantic_event_id
        )
        if not rows:
            if event.visual_leader_asset_id or event.result_asset_ids:
                diagnostics.append(StorySemanticDiagnostic(
                    scene_id=scene.id, beat_id=beat.id, event_id=event.semantic_event_id,
                    asset_ids=list(filter(None, [event.visual_leader_asset_id,
                                                 *event.result_asset_ids])),
                    conflict_type="UNPROVEN_EVENT_CARRIER",
                    authority_sources=["FINAL_PACKAGE_SEMANTIC_EVENT", "STORY_CARRIER_PROOF"],
                    chosen_authority="STORY_CARRIER_PROOF", fallback="CONTEXT",
                    abstained=True,
                ))
            continue

        def proven(semantic_ids: tuple[str, ...]) -> list[str]:
            return list(dict.fromkeys(
                row.asset_id for row in rows
                if row.semantic_unit_id in semantic_ids
            ))

        leader = proven((event.visual_leader_asset_id,)) if event.visual_leader_asset_id else []
        participants = proven(event.participant_asset_ids)
        results = proven(event.result_asset_ids)
        contexts = proven(event.context_asset_ids)
        text_anchors = proven((event.text_anchor_asset_id,)) if event.text_anchor_asset_id else []
        for label, authored, resolved in (
            ("LEADER", event.visual_leader_asset_id, leader),
            ("RESULT", event.result_asset_ids, results),
        ):
            if authored and not resolved:
                diagnostics.append(StorySemanticDiagnostic(
                    scene_id=scene.id, beat_id=beat.id, event_id=event.semantic_event_id,
                    asset_ids=([authored] if isinstance(authored, str) else list(authored)),
                    conflict_type=f"UNPROVEN_{label}_CARRIER",
                    authority_sources=["FINAL_PACKAGE_SEMANTIC_EVENT", "STORY_CARRIER_PROOF"],
                    chosen_authority="STORY_CARRIER_PROOF", fallback="CONTEXT",
                    source_values={"authored_semantic_ids": str(authored)},
                    abstained=True,
                ))
        if event.visual_leader_asset_id and leader:
            competing = [
                unit.asset_id for unit in scene.assets
                if unit.asset_id != event.visual_leader_asset_id
                and str(unit.visual_focus).upper().endswith("PRIMARY")
                and unit.asset_id in {row.semantic_unit_id for row in rows}
            ]
            if competing:
                diagnostics.append(StorySemanticDiagnostic(
                    scene_id=scene.id, beat_id=beat.id, event_id=event.semantic_event_id,
                    asset_ids=[event.visual_leader_asset_id, *competing],
                    conflict_type="LEADER_VISUAL_FOCUS_CONFLICT",
                    authority_sources=["FINAL_PACKAGE_SEMANTIC_EVENT", "FINAL_PACKAGE_VISUAL_FOCUS"],
                    chosen_authority="FINAL_PACKAGE_SEMANTIC_EVENT",
                ))
        if event.result_asset_ids and inferred_results:
            diagnostics.append(StorySemanticDiagnostic(
                scene_id=scene.id, beat_id=beat.id, event_id=event.semantic_event_id,
                asset_ids=[*event.result_asset_ids, *sorted(inferred_results)],
                conflict_type="EVENT_INFERRED_RESULT_CONFLICT",
                authority_sources=["FINAL_PACKAGE_SEMANTIC_EVENT", "TEXT_INFERENCE"],
                chosen_authority="FINAL_PACKAGE_SEMANTIC_EVENT",
            ))
        if event.needs_review or event.ambiguity_reason or event.confidence < 1.0:
            diagnostics.append(StorySemanticDiagnostic(
                scene_id=scene.id, beat_id=beat.id, event_id=event.semantic_event_id,
                asset_ids=list(dict.fromkeys(row.asset_id for row in rows)),
                conflict_type=("EVENT_REVIEW" if event.needs_review or event.ambiguity_reason
                               else "EVENT_CONFIDENCE_PROVENANCE"),
                authority_sources=["FINAL_PACKAGE_SEMANTIC_EVENT"],
                chosen_authority="EXISTING_CARRIER_POLICY",
                source_values={"needs_review": event.needs_review,
                               "ambiguity_reason": event.ambiguity_reason,
                               "confidence": event.confidence},
            ))
        relation_kinds = list(dict.fromkeys(
            relation.relation_type for relation in scene.relations
            if relation.subject_asset_id in {
                event.visual_leader_asset_id, *event.participant_asset_ids
            }
            and relation.object_asset_id in {
                *event.participant_asset_ids, *event.result_asset_ids
            }
            and relation.subject_asset_id in {row.semantic_unit_id for row in rows}
            and relation.object_asset_id in {row.semantic_unit_id for row in rows}
        ))
        starts = [row.spoken_start for row in rows if row.spoken_start is not None]
        ends = [row.spoken_end for row in rows if row.spoken_end is not None]
        records.append(StoryEventAuthority(
            event_id=event.semantic_event_id, sequence_order=event.sequence_order,
            leader_asset_ids=leader, participant_asset_ids=participants,
            result_asset_ids=results, context_asset_ids=contexts,
            text_anchor_asset_ids=text_anchors,
            dependency_ids=list(event.depends_on_event_ids),
            script_char_start=(event.script_span.global_char_start if event.script_span else None),
            script_char_end=(event.script_span.global_char_end if event.script_span else None),
            spoken_start=min(starts) if starts else None,
            spoken_end=max(ends) if ends else None,
            confidence=event.confidence, needs_review=event.needs_review,
            ambiguity_reason=event.ambiguity_reason,
            relation_kinds=relation_kinds,
        ))
    return records, diagnostics
