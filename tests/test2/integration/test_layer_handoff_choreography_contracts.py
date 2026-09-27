from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from app.shared.handoff import LayerHandoffValidator
from tests.test2.integration.handoff_contract_support import (
    build_handoff_case,
    expect_handoff_failure,
)


def test_choreography_handoff_rejects_event_not_owned_by_story(tmp_path: Path) -> None:
    _package, _transcript, assets, story, choreography, *_ = build_handoff_case(tmp_path)
    first = choreography.directives[0]
    bad_flow = replace(first.event_flows[0], event_id="FOREIGN_EVENT")
    bad_directive = replace(first, event_flows=(bad_flow, *first.event_flows[1:]))
    broken = replace(
        choreography,
        directives=(bad_directive, *choreography.directives[1:]),
    )
    error = expect_handoff_failure(
        "CHOREOGRAPHY_HANDOFF_CONTRACT_VIOLATIONS",
        lambda: LayerHandoffValidator.require_choreography_for_composition(
            story=story, assets=assets, choreography=broken
        ),
    )
    assert any(
        row["kind"] == "choreography_event_not_owned_by_story"
        for row in error.details["violations"]
    )

def test_composition_handoff_rejects_duplicate_asset_geometry(tmp_path: Path) -> None:
    _package, _transcript, assets, story, _choreography, composition, *_ = build_handoff_case(tmp_path)
    broken = list(composition)
    first = broken[0]
    broken[0] = first.model_copy(update={"items": [*first.items, first.items[0]]})
    error = expect_handoff_failure(
        "COMPOSITION_HANDOFF_CONTRACT_VIOLATIONS",
        lambda: LayerHandoffValidator.require_composition_for_motion(
            story=story, assets=assets, composition=broken
        ),
    )
    assert any(
        row["kind"] == "duplicate_composition_asset"
        for row in error.details["violations"]
    )

def test_choreography_handoff_rejects_sequence_coverage_gap(tmp_path: Path) -> None:
    _package, _transcript, assets, story, choreography, *_ = build_handoff_case(tmp_path)
    assert choreography.sequences and choreography.sequences[0].beat_ids
    first = choreography.sequences[0]
    broken_first = replace(first, beat_ids=first.beat_ids[1:])
    broken = replace(
        choreography,
        sequences=(broken_first, *choreography.sequences[1:]),
    )
    error = expect_handoff_failure(
        "CHOREOGRAPHY_HANDOFF_CONTRACT_VIOLATIONS",
        lambda: LayerHandoffValidator.require_choreography_for_composition(
            story=story, assets=assets, choreography=broken
        ),
    )
    assert any(
        row["kind"] == "sequence_coverage_does_not_match_story"
        for row in error.details["violations"]
    )

def test_choreography_handoff_rejects_missing_dependency(tmp_path: Path) -> None:
    _package, _transcript, assets, story, choreography, *_ = build_handoff_case(tmp_path)
    directive_index = next(
        index
        for index, directive in enumerate(choreography.directives)
        if directive.event_flows
    )
    directive = choreography.directives[directive_index]
    flow = directive.event_flows[-1]
    broken_flow = replace(flow, dependency_ids=("MISSING_EVENT",))
    flows = list(directive.event_flows)
    flows[-1] = broken_flow
    directives = list(choreography.directives)
    directives[directive_index] = replace(directive, event_flows=tuple(flows))
    broken = replace(choreography, directives=tuple(directives))
    error = expect_handoff_failure(
        "CHOREOGRAPHY_HANDOFF_CONTRACT_VIOLATIONS",
        lambda: LayerHandoffValidator.require_choreography_for_composition(
            story=story, assets=assets, choreography=broken
        ),
    )
    assert any(
        row["kind"] == "choreography_dependency_missing_from_beat"
        for row in error.details["violations"]
    )

def test_composition_handoff_rejects_missing_independent_asset(tmp_path: Path) -> None:
    _package, _transcript, assets, story, _choreography, composition, *_ = build_handoff_case(tmp_path)
    first = composition[0]
    victim = next(
        item
        for item in first.items
        if next(asset for asset in assets if asset.id == item.asset_id).can_animate_independently
    )
    broken = list(composition)
    broken[0] = first.model_copy(
        update={"items": [item for item in first.items if item.asset_id != victim.asset_id]}
    )
    error = expect_handoff_failure(
        "COMPOSITION_HANDOFF_CONTRACT_VIOLATIONS",
        lambda: LayerHandoffValidator.require_composition_for_motion(
            story=story, assets=assets, composition=broken
        ),
    )
    row = next(
        row
        for row in error.details["violations"]
        if row["kind"] == "composition_missing_independent_assets"
    )
    assert victim.asset_id in row["asset_ids"]

