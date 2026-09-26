from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
import json
from typing import Iterable

from app.models import RenderPlan
from app.recovery.detector import DetectedIssue


@dataclass(frozen=True, slots=True)
class RecoveryCandidateAssessment:
    accepted: bool
    target_resolved: bool
    before_issue_count: int
    after_issue_count: int
    introduced_issue_keys: tuple[str, ...]
    regressed_issue_counts: tuple[str, ...]
    semantic_authority_changed: bool
    reason: str

    def to_details(self) -> dict:
        return asdict(self)


class RecoveryCandidateEvaluator:
    """Accept recovery candidates only when they improve monotonically.

    Recovery may change implementation state but must never silently trade one defect
    for another or alter Final-Package-derived semantic authority.
    """

    @staticmethod
    def issue_key(issue: DetectedIssue) -> str:
        context = json.dumps(issue.context, ensure_ascii=False, sort_keys=True, default=str)
        return f"{issue.code}:{context}"

    @classmethod
    def semantic_authority_signature(cls, plan: RenderPlan) -> str:
        beats: list[dict] = []
        for beat in sorted(plan.story, key=lambda row: (row.start, row.end, row.id)):
            context = beat.semantic_context
            context_payload = None
            if context is not None:
                context_payload = {
                    "scene_purpose": context.scene_purpose,
                    "scene_visual_concept": context.scene_visual_concept,
                    "entities": [row.model_dump(mode="json") for row in context.entities],
                    "relations": [row.model_dump(mode="json") for row in context.relations],
                    "subject_unit_ids": list(context.subject_unit_ids),
                    "object_unit_ids": list(context.object_unit_ids),
                    "result_unit_ids": list(context.result_unit_ids),
                    "focus_unit_ids": list(context.focus_unit_ids),
                    "visual_states": context.visual_states,
                    "continuity_by_unit": context.continuity_by_unit,
                    "narrative_functions": list(context.narrative_functions),
                    "semantic_intents": list(context.semantic_intents),
                    "continuity_relation": context.continuity_relation,
                }
            activations = []
            for row in sorted(beat.asset_activations, key=lambda item: item.asset_id):
                activations.append({
                    "asset_id": row.asset_id,
                    "semantic_unit_id": row.semantic_unit_id,
                    "semantic_group_id": row.semantic_group_id,
                    "binding_type": row.binding_type,
                    "semantic_parent_id": row.semantic_parent_id,
                    "group_animation_policy": row.group_animation_policy,
                    "visual_focus": row.visual_focus,
                    "visual_state": row.visual_state,
                    "continuity": row.continuity,
                    "semantic_event_id": row.semantic_event_id,
                    "semantic_event_order": row.semantic_event_order,
                    "semantic_event_roles": list(row.semantic_event_roles),
                    "semantic_event_dependency_ids": list(row.semantic_event_dependency_ids),
                    "compound_visual_classification": row.compound_visual_classification,
                    "internal_progression_unavailable": row.internal_progression_unavailable,
                })
            proxies = [
                {
                    "asset_id": row.asset_id,
                    "semantic_unit_id": row.semantic_unit_id,
                    "semantic_parent_id": row.semantic_parent_id,
                    "semantic_event_id": row.semantic_event_id,
                    "semantic_event_order": row.semantic_event_order,
                    "semantic_event_roles": list(row.semantic_event_roles),
                    "semantic_event_dependency_ids": list(row.semantic_event_dependency_ids),
                    "authority": row.authority,
                    "visual_focus": row.visual_focus,
                }
                for row in sorted(
                    beat.semantic_event_proxies,
                    key=lambda item: (item.asset_id, item.semantic_event_id, item.semantic_unit_id),
                )
            ]
            beats.append({
                "beat_id": beat.id,
                "scene_id": beat.scene_id,
                "context": context_payload,
                "activations": activations,
                "proxies": proxies,
            })
        return json.dumps(beats, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    @classmethod
    def evaluate(
        cls,
        *,
        target: DetectedIssue,
        before_issues: Iterable[DetectedIssue],
        after_issues: Iterable[DetectedIssue],
        before_plan: RenderPlan | None = None,
        candidate_plan: RenderPlan | None = None,
    ) -> RecoveryCandidateAssessment:
        before = list(before_issues)
        after = list(after_issues)
        before_keys = Counter(cls.issue_key(row) for row in before)
        after_keys = Counter(cls.issue_key(row) for row in after)
        target_key = cls.issue_key(target)
        target_resolved = after_keys[target_key] < before_keys[target_key]
        introduced = tuple(sorted((after_keys - before_keys).elements()))

        before_codes = Counter(row.code for row in before)
        after_codes = Counter(row.code for row in after)
        regressed_counts = tuple(
            sorted(
                f"{code}:{before_codes[code]}->{after_codes[code]}"
                for code in after_codes
                if after_codes[code] > before_codes[code]
            )
        )

        semantic_changed = False
        if before_plan is not None or candidate_plan is not None:
            if before_plan is None or candidate_plan is None:
                semantic_changed = True
            else:
                semantic_changed = (
                    cls.semantic_authority_signature(before_plan)
                    != cls.semantic_authority_signature(candidate_plan)
                )

        if semantic_changed:
            reason = "semantic_authority_changed"
        elif not target_resolved:
            reason = "target_issue_not_resolved"
        elif introduced:
            reason = "new_issue_introduced"
        elif regressed_counts:
            reason = "issue_count_regressed"
        elif len(after) >= len(before):
            reason = "no_strict_improvement"
        else:
            reason = "monotonic_improvement"

        return RecoveryCandidateAssessment(
            accepted=(reason == "monotonic_improvement"),
            target_resolved=target_resolved,
            before_issue_count=len(before),
            after_issue_count=len(after),
            introduced_issue_keys=introduced,
            regressed_issue_counts=regressed_counts,
            semantic_authority_changed=semantic_changed,
            reason=reason,
        )
