from __future__ import annotations

import os
from pathlib import Path

from tests.test1.canonical import test_authority as authority_tests
from tests.test1.canonical import test_unified_loader as loader_tests
from tests.test1.certification import test_canonical_correctness as correctness_tests
from tests.test1.certification import test_canonical_immutability as immutability_tests
from tests.test1.certification import test_cross_package_state as state_tests
from tests.test1.certification import test_performance_sanity as performance_tests
from tests.test1.certification import test_typed_contracts as typed_tests
from tests.test1.certification.test_generated_full_layer_matrix import (
    FULL_LAYER_SEEDS,
    _plan,
)
from tests.test1.certification.test_raw_data_boundary import (
    contract_bucket_violations,
    legacy_contract_violations,
)
from tests.test1.certification.test_real_package_planning import (
    _REAL_PACKAGES,
    certify_real_package_to_render_plan,
)
from tests.test1.factory import seeded_disk_shape


def test_master_engine_compatibility_certification(tmp_path: Path) -> None:
    """One executable entry point covering the complete Canonical certification."""

    # Unified loader / enums / optionals / authority / semantic preservation.
    loader_tests.test_unified_loader_preserves_semantic_counts_and_identity(tmp_path / "loader")
    loader_tests.test_unified_loader_maps_closed_domains_to_enums(tmp_path / "enums")
    loader_tests.test_optional_metadata_does_not_change_semantic_signature(tmp_path / "optionals")
    authority_tests.test_semantic_authority_is_centralized_and_deterministic()
    correctness_tests.test_generated_semantic_truth_is_preserved_through_canonicalization(
        tmp_path / "correctness"
    )

    # Deep immutability / typed downstream / global raw boundary / contracts ownership.
    immutability_tests.test_canonical_records_are_not_mapping_compatibility_objects(
        tmp_path / "immutability-record"
    )
    immutability_tests.test_canonical_semantic_truth_is_deeply_immutable(
        tmp_path / "immutability-deep"
    )
    typed_tests.test_public_package_consumers_declare_canonical_runtime_contract()
    assert legacy_contract_violations() == []
    assert contract_bucket_violations() == []

    # The dedicated full-layer module owns the expanded 250+ case matrix.
    # Master certification executes a deterministic representative sample and
    # verifies that the exhaustive matrix remains configured at release strength.
    assert len(FULL_LAYER_SEEDS) >= 250
    sample_step = max(1, len(FULL_LAYER_SEEDS) // 10)
    master_sample_seeds = FULL_LAYER_SEEDS[::sample_step]
    generated_checked = 0
    for seed in master_sample_seeds:
        canonical, story, choreography, composition, motion, text, plan = _plan(
            tmp_path / "full-layer" / str(seed), seeded_disk_shape(seed)
        )
        asset_ids = set(canonical.asset_by_id)
        event_ids = set(canonical.event_by_id)
        beat_ids = {beat.id for beat in story}
        assert {asset.id for asset in plan.assets} == asset_ids
        assert all(
            activation.asset_id in asset_ids
            and (
                activation.semantic_event_id is None
                or activation.semantic_event_id in event_ids
            )
            for beat in story
            for activation in beat.asset_activations
        )
        assert all(item.asset_id in asset_ids for beat in composition for item in beat.items)
        assert all(cue.asset_id in asset_ids and cue.beat_id in beat_ids for cue in motion)
        assert all(cue.beat_id in beat_ids for cue in text.cues)
        assert choreography.directives
        generated_checked += 1
    assert generated_checked == len(master_sample_seeds)

    # Same-process state isolation and large canonicalization sanity.
    state_tests.test_sequential_packages_do_not_leak_state_between_runs(
        tmp_path / "cross-package"
    )
    performance_tests.test_large_unified_canonicalization_has_no_combinatorial_explosion(
        tmp_path / "performance"
    )

    # Strict release mode closes the four accepted real packages through RenderPlan.
    real_status: dict[str, str] = {}
    corpus_raw = os.getenv("HEXA_REAL_PACKAGE_CORPUS")
    strict = os.getenv("HEXA_REQUIRE_REAL_PACKAGE_CORPUS") == "1"
    if strict and not corpus_raw:
        raise AssertionError(
            "REAL PACKAGE CERTIFICATION BLOCKED: HEXA_REAL_PACKAGE_CORPUS is unset"
        )
    if corpus_raw:
        corpus = Path(corpus_raw)
        for filename in _REAL_PACKAGES:
            result = certify_real_package_to_render_plan(
                corpus, filename, tmp_path / "real" / filename
            )
            assert result.story_beats == result.scenes
            assert result.motion_cues == result.runtime_assets
            real_status[filename] = "PASS"
    else:
        real_status = {filename: "BLOCKED_DEV_CORPUS_UNAVAILABLE" for filename in _REAL_PACKAGES}

    print("TEST1 MASTER CERTIFICATION")
    print("Final Package boundary: PASS")
    print("Unified package canonicalization: PASS")
    print("Canonical semantic preservation: PASS")
    print("Canonical immutability: PASS")
    print("Raw-data leakage guard: PASS")
    print("Typed downstream contracts: PASS")
    print("Generic contracts folder removed: PASS")
    print(f"Generated full-layer matrix configured: {len(FULL_LAYER_SEEDS)} scenarios")
    print(f"Master representative full-layer sample: {generated_checked} PASS")
    print("Cross-package isolation: PASS")
    print("Performance sanity: PASS")
    for filename, status in real_status.items():
        print(f"{filename}: {status}")
