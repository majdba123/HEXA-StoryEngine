from __future__ import annotations

from collections import Counter
from pathlib import Path

from tests.test2.quality_rule_ledger import (
    LEGACY_QA_RUNTIME_FILES,
    MIGRATION_COMPLETE,
    MigrationState,
    QUALITY_RULES,
    RuleKind,
)


ROOT = Path(__file__).resolve().parents[2]


def test_master_qa_rule_ledger_has_unique_complete_identity() -> None:
    ids = [rule.id for rule in QUALITY_RULES]
    assert ids
    assert [rule_id for rule_id, count in Counter(ids).items() if count > 1] == []
    assert all(rule.legacy_source in LEGACY_QA_RUNTIME_FILES for rule in QUALITY_RULES)
    assert all(rule.owner for rule in QUALITY_RULES)
    assert all(rule.test_module.startswith("tests/test2/") for rule in QUALITY_RULES)


def test_master_qa_tracks_every_legacy_runtime_quality_surface() -> None:
    represented = {rule.legacy_source for rule in QUALITY_RULES}
    # failure_identity is a helper used by QA reports, not an independent quality rule.
    expected_rule_sources = LEGACY_QA_RUNTIME_FILES - {"app/qa/failure_identity.py"}
    assert represented == expected_rule_sources


def test_master_qa_owner_modules_exist_or_are_declared_cross_layer() -> None:
    missing = sorted({
        rule.owner
        for rule in QUALITY_RULES
        if rule.owner != "cross_layer"
        and not (ROOT / rule.owner).is_file()
    })
    assert missing == []


def test_master_qa_completion_gate_is_strict() -> None:
    if not MIGRATION_COMPLETE:
        # During the migration Test1 remains the system-level safety net while Test2
        # is filled owner by owner.  No rule may be falsely marked complete without a
        # real Test2 module on disk.
        falsely_complete = [
            rule.id
            for rule in QUALITY_RULES
            if rule.state in {
                MigrationState.MIGRATED,
                MigrationState.RETAINED_PROOF,
                MigrationState.EVIDENCE_ONLY,
            }
            and not (ROOT / rule.test_module).is_file()
        ]
        assert falsely_complete == []
        return

    pending = [rule.id for rule in QUALITY_RULES if rule.state == MigrationState.PENDING]
    assert pending == []

    missing_tests = sorted({
        rule.test_module
        for rule in QUALITY_RULES
        if not (ROOT / rule.test_module).is_file()
    })
    assert missing_tests == []

    # Once complete, the old runtime QA architecture must be physically gone.
    assert not (ROOT / "app" / "qa").exists()
    assert not (ROOT / "app" / "story" / "sync_qa.py").exists()
    assert not (ROOT / "app" / "diagnostics" / "storytelling.py").exists()
    assert not (ROOT / "app" / "diagnostics" / "asset_usage.py").exists()

    production_sources = {
        path.relative_to(ROOT): path.read_text(encoding="utf-8")
        for path in (ROOT / "app").rglob("*.py")
    }
    forbidden = (
        "from app.qa",
        "import app.qa",
        "StorySyncQA",
        "StorytellingValidator",
        "AssetUsageValidator",
        "AuthoringVisualQA",
        "MotionInteractionQA",
        "ChoreographyRhythmQA",
        "SceneContinuityQA",
        "SemanticLifetimeQA",
        "RenderedMotionQA",
        "RenderedVisualQA",
    )
    violations = {
        str(path): [token for token in forbidden if token in source]
        for path, source in production_sources.items()
        if any(token in source for token in forbidden)
    }
    assert violations == []

    # Encoded facts remain proof after FFmpeg; they are not pre-render QA.
    encoded_rules = [rule for rule in QUALITY_RULES if rule.kind == RuleKind.ENCODED_PROOF]
    assert encoded_rules
    assert all(rule.owner == "app/render/verification.py" for rule in encoded_rules)
