import pytest

from app.qa.failure_identity import violation_failure_details
from app.qa.motion_semantics import (
    MotionInteractionQA,
    MotionInteractionReport,
    MotionInteractionViolation,
)
from app.shared.errors import InvalidPackageError, StageFailedError


def test_stage_failure_exposes_specific_effective_code() -> None:
    error = StageFailedError(
        "motion invalid",
        details={"code": "MOTION_INFEASIBLE_BEFORE_RENDER", "asset_id": "a"},
    )
    assert error.code == "STAGE_FAILED"
    assert error.effective_code == "MOTION_INFEASIBLE_BEFORE_RENDER"


def test_error_without_detail_code_keeps_category_code() -> None:
    error = InvalidPackageError("bad package", details={"scene_id": "s1"})
    assert error.code == "INVALID_PACKAGE"
    assert error.effective_code == "INVALID_PACKAGE"


def test_blank_detail_code_does_not_hide_category() -> None:
    error = StageFailedError("bad", details={"code": "   "})
    assert error.effective_code == "STAGE_FAILED"


def test_qa_single_failure_class_surfaces_specific_code() -> None:
    report = MotionInteractionReport(
        checked_segments=1,
        checked_relations=0,
        violations=(
            MotionInteractionViolation(
                code="SEGMENT_PAST_HANDOFF",
                beat_id="beat-1",
                asset_id="asset-1",
                event_id="event-1",
                detail="segment exceeds semantic handoff",
            ),
        ),
    )

    with pytest.raises(StageFailedError) as exc_info:
        MotionInteractionQA.require(report)

    assert exc_info.value.effective_code == "SEGMENT_PAST_HANDOFF"
    assert exc_info.value.details["violation_codes"] == ["SEGMENT_PAST_HANDOFF"]
    assert exc_info.value.details["violation_count"] == 1


class _Violation:
    def __init__(self, code: str) -> None:
        self.code = code


def test_qa_mixed_failure_classes_keep_codes_and_use_aggregate_identity() -> None:
    details = violation_failure_details(
        [_Violation("MOTION_TOO_FAST"), _Violation("RENDERED_SEGMENT_INACTIVE")],
        aggregate_code="RENDERED_MOTION_CONTRACT_VIOLATIONS",
    )

    assert details["code"] == "RENDERED_MOTION_CONTRACT_VIOLATIONS"
    assert details["violation_codes"] == [
        "MOTION_TOO_FAST",
        "RENDERED_SEGMENT_INACTIVE",
    ]
    assert details["violation_count"] == 2
