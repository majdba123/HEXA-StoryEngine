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
