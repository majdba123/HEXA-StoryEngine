from __future__ import annotations

from app.models import RenderPlan, StoryBeat, StorySemanticContext
from app.recovery import RecoveryCandidateEvaluator
from app.recovery.detector import DetectedIssue


def _plan(intent: str = "SAFE") -> RenderPlan:
    return RenderPlan(
        width=320, height=180, fps=30, duration=1.0,
        story=[StoryBeat(
            id="beat-1", scene_id="scene-1", start=0.0, end=1.0,
            narration="test", action="EXPLAIN",
            semantic_context=StorySemanticContext(semantic_intents=[intent]),
        )],
        composition=[], motion=[], assets=[],
    )


def test_recovery_candidate_accepts_strict_monotonic_improvement() -> None:
    target = DetectedIssue("BAD_HANDOFF", "bad", {"beat_id": "b1"})
    secondary = DetectedIssue("LOW_SCREEN_OCCUPANCY", "low", {"beat_id": "b2"})

    result = RecoveryCandidateEvaluator.evaluate(
        target=target,
        before_issues=[target, secondary],
        after_issues=[secondary],
        before_plan=_plan(),
        candidate_plan=_plan(),
    )

    assert result.accepted
    assert result.reason == "monotonic_improvement"
    assert result.before_issue_count == 2
    assert result.after_issue_count == 1
    assert not result.semantic_authority_changed


def test_recovery_candidate_rejects_issue_tradeoff() -> None:
    target = DetectedIssue("BAD_HANDOFF", "bad", {"beat_id": "b1"})
    introduced = DetectedIssue("MULTI_ELEMENT_POP", "pop", {"beat_id": "b2"})

    result = RecoveryCandidateEvaluator.evaluate(
        target=target,
        before_issues=[target],
        after_issues=[introduced],
        before_plan=_plan(),
        candidate_plan=_plan(),
    )

    assert not result.accepted
    assert result.reason == "new_issue_introduced"
    assert result.introduced_issue_keys


def test_recovery_candidate_rejects_semantic_authority_change() -> None:
    target = DetectedIssue("BAD_HANDOFF", "bad", {"beat_id": "b1"})

    result = RecoveryCandidateEvaluator.evaluate(
        target=target,
        before_issues=[target],
        after_issues=[],
        before_plan=_plan("ORIGINAL"),
        candidate_plan=_plan("CHANGED"),
    )

    assert not result.accepted
    assert result.reason == "semantic_authority_changed"
    assert result.semantic_authority_changed


def test_recovery_candidate_rejects_same_code_new_instance() -> None:
    target = DetectedIssue("ASSET_BAD_CUTOUT", "bad a", {"asset_id": "a"})
    replacement = DetectedIssue("ASSET_BAD_CUTOUT", "bad b", {"asset_id": "b"})

    result = RecoveryCandidateEvaluator.evaluate(
        target=target,
        before_issues=[target],
        after_issues=[replacement],
        before_plan=_plan(),
        candidate_plan=_plan(),
    )

    assert not result.accepted
    assert result.reason == "new_issue_introduced"
