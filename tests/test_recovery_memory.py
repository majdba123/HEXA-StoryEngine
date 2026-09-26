import json
from pathlib import Path

from app.recovery.builtins import BUILTIN_ISSUES
from app.recovery.manager import RecoveryManager
from app.recovery.models import KnownIssue, RecoveryStatus
from app.recovery.policy import FailureDisposition, failure_policy


def test_recovery_records_only_after_post_fix_validation(tmp_path: Path) -> None:
    manager = RecoveryManager(tmp_path)

    result = manager.handle(
        code="LOW_SCREEN_OCCUPANCY",
        context={"beat_id": "beat-1"},
        attempt=1,
    )
    assert result is not None
    assert result.invalidate_from_stage == "composition"
    assert not (tmp_path / "recovery-history.jsonl").exists()

    manager.record_outcome(
        code="LOW_SCREEN_OCCUPANCY",
        job_id="job-a",
        package_id="package-a",
        attempt=1,
        handler_result=result,
        success=True,
        details={"qa": "pass"},
    )

    rows = [
        json.loads(line)
        for line in (tmp_path / "recovery-history.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert rows[-1]["issue_code"] == "LOW_SCREEN_OCCUPANCY"
    assert rows[-1]["package_id"] == "package-a"
    assert rows[-1]["success"] is True


def test_known_issue_registry_persists_across_manager_instances(tmp_path: Path) -> None:
    first = RecoveryManager(tmp_path)
    assert first.registry.get("AUDIO_VIDEO_DRIFT") is not None

    second = RecoveryManager(tmp_path)
    issue = second.registry.get("AUDIO_VIDEO_DRIFT")
    assert issue is not None
    assert issue.status.value == "proven"
    assert issue.handler == "remux_audio"


def test_builtin_policy_version_migrates_stale_proven_recovery(tmp_path: Path) -> None:
    first = RecoveryManager(tmp_path)
    first.registry.upsert(KnownIssue(
        code="ASSET_WHITE_HALO",
        description="legacy optimistic policy",
        affected_stage="cutout",
        handler="retry_cutout",
        status=RecoveryStatus.proven,
        handler_version=1,
    ))

    migrated = RecoveryManager(tmp_path)
    issue = migrated.registry.get("ASSET_WHITE_HALO")

    assert issue is not None
    assert issue.handler_version == 2
    assert issue.status == RecoveryStatus.candidate
    assert migrated.handle(
        code="ASSET_WHITE_HALO",
        context={"asset_id": "a"},
        attempt=1,
    ) is None


def test_builtin_seed_does_not_overwrite_newer_local_policy(tmp_path: Path) -> None:
    first = RecoveryManager(tmp_path)
    first.registry.upsert(KnownIssue(
        code="ASSET_WHITE_HALO",
        description="locally verified future policy",
        affected_stage="cutout",
        handler="retry_cutout",
        status=RecoveryStatus.proven,
        handler_version=99,
    ))

    reloaded = RecoveryManager(tmp_path)
    issue = reloaded.registry.get("ASSET_WHITE_HALO")

    assert issue is not None
    assert issue.handler_version == 99
    assert issue.status == RecoveryStatus.proven


def test_historical_failure_policies_block_blind_recovery_for_deterministic_contracts(
    tmp_path: Path,
) -> None:
    manager = RecoveryManager(tmp_path)
    policy = failure_policy("MOTION_TOO_FAST")
    assert policy is not None
    assert policy.disposition == FailureDisposition.PREVENT
    assert policy.semantic_authority_change_allowed is False
    assert manager.handle(code="MOTION_TOO_FAST", context={}, attempt=1) is None


def test_encoded_inactivity_is_post_render_proof_not_identical_rerender_recovery(
    tmp_path: Path,
) -> None:
    manager = RecoveryManager(tmp_path)
    policy = failure_policy("RENDERED_SEGMENT_INACTIVE")
    assert policy is not None
    assert policy.disposition == FailureDisposition.POST_RENDER_PROOF
    assert manager.handle(code="RENDERED_SEGMENT_INACTIVE", context={}, attempt=1) is None


def test_text_layout_remains_explicit_bounded_recovery(tmp_path: Path) -> None:
    manager = RecoveryManager(tmp_path)
    policy = failure_policy("TEXT_LAYOUT_REFERENCE_VIOLATION")
    assert policy is not None
    assert policy.disposition == FailureDisposition.RECOVER
    assert manager.handle(
        code="TEXT_LAYOUT_REFERENCE_VIOLATION",
        context={},
        attempt=1,
    ) is not None


def test_all_known_historical_engine_failures_have_declared_disposition() -> None:
    codes = {
        "MISSING_RELATION_TIMELINE",
        "MISSING_RESULT_PAYOFF",
        "MISSING_TARGET_REACTION",
        "MOTION_BELOW_PERCEPTUAL_FLOOR",
        "RENDERED_SEGMENT_INACTIVE",
        "MOTION_TOO_FAST",
        "MOTION_CREATES_COLLISION",
        "SEGMENT_PAST_HANDOFF",
        "TERMINAL_EXIT_ON_PERSISTENT_ASSET",
        "TEXT_LAYOUT_REFERENCE_VIOLATION",
        "FFMPEG_UNAVAILABLE",
        "FFMPEG_FILTER_FILE_UNSUPPORTED",
    }
    missing = sorted(code for code in codes if failure_policy(code) is None)
    assert missing == []


def test_every_builtin_issue_has_declared_failure_policy() -> None:
    missing = sorted(
        issue.code
        for issue in BUILTIN_ISSUES
        if failure_policy(issue.code) is None
    )
    assert missing == []


def test_white_halo_candidate_policy_cannot_be_used_as_proven_recovery(tmp_path: Path) -> None:
    manager = RecoveryManager(tmp_path)
    policy = failure_policy("ASSET_WHITE_HALO")
    assert policy is not None
    assert policy.disposition == FailureDisposition.PREVENT
    assert manager.handle(
        code="ASSET_WHITE_HALO",
        context={"asset_id": "a"},
        attempt=1,
    ) is None
