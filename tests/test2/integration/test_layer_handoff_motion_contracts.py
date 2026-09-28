from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from app.shared.handoff import LayerHandoffValidator
from tests.test2.integration.handoff_contract_support import (
    build_handoff_case,
    expect_handoff_failure,
)


def test_motion_handoff_rejects_one_beat_asset_drop(tmp_path: Path) -> None:
    (
        _package,
        _transcript,
        assets,
        story,
        choreography,
        composition,
        motion,
        _text,
    ) = build_handoff_case(tmp_path)
    victim = next(cue for cue in motion if cue.beat_id == story[0].id)
    broken = [cue for cue in motion if cue is not victim]
    error = expect_handoff_failure(
        "MOTION_HANDOFF_CONTRACT_VIOLATIONS",
        lambda: LayerHandoffValidator.require_motion_for_text_and_render(
            story=story,
            assets=assets,
            composition=composition,
            choreography=choreography,
            motion=broken,
        ),
    )
    row = next(
        row
        for row in error.details["violations"]
        if row["kind"] == "motion_does_not_cover_composition"
    )
    assert victim.asset_id in row["missing"]

def test_motion_handoff_rejects_foreign_semantic_event(tmp_path: Path) -> None:
    (
        _package,
        _transcript,
        assets,
        story,
        choreography,
        composition,
        motion,
        _text,
    ) = build_handoff_case(tmp_path)
    cue_index = next(index for index, cue in enumerate(motion) if cue.segments)
    cue = motion[cue_index]
    segment = cue.segments[0].model_copy(update={"semantic_event_id": "FOREIGN_EVENT"})
    broken = list(motion)
    broken[cue_index] = cue.model_copy(update={"segments": [segment, *cue.segments[1:]]})
    error = expect_handoff_failure(
        "MOTION_HANDOFF_CONTRACT_VIOLATIONS",
        lambda: LayerHandoffValidator.require_motion_for_text_and_render(
            story=story,
            assets=assets,
            composition=composition,
            choreography=choreography,
            motion=broken,
        ),
    )
    assert any(
        row["kind"] == "motion_segment_event_not_owned_by_story"
        for row in error.details["violations"]
    )

def test_motion_handoff_rejects_nonterminal_geometry_drift(tmp_path: Path) -> None:
    (
        _package,
        _transcript,
        assets,
        story,
        choreography,
        composition,
        motion,
        _text,
    ) = build_handoff_case(tmp_path)
    cue_index = next(
        index
        for index, cue in enumerate(motion)
        if any(
            segment.program.get("terminal_behavior") != "LEAVE"
            for segment in cue.segments
        )
    )
    cue = motion[cue_index]
    seg_index = next(
        index
        for index, segment in enumerate(cue.segments)
        if segment.program.get("terminal_behavior") != "LEAVE"
    )
    segment = cue.segments[seg_index]
    program = dict(segment.program)
    keyframes = [dict(frame) for frame in program["keyframes"]]
    keyframes[-1]["dx"] = 0.02
    program["keyframes"] = keyframes
    bad_segment = segment.model_copy(update={"program": program})
    segments = list(cue.segments)
    segments[seg_index] = bad_segment
    broken = list(motion)
    broken[cue_index] = cue.model_copy(update={"segments": segments})

    error = expect_handoff_failure(
        "MOTION_HANDOFF_CONTRACT_VIOLATIONS",
        lambda: LayerHandoffValidator.require_motion_for_text_and_render(
            story=story,
            assets=assets,
            composition=composition,
            choreography=choreography,
            motion=broken,
        ),
    )
    assert any(
        row["kind"] == "motion_segment_does_not_restore_composition_identity"
        for row in error.details["violations"]
    )

def test_motion_handoff_deadline_boundary_is_inclusive_then_fail_closed(tmp_path: Path) -> None:
    (
        _package,
        _transcript,
        assets,
        story,
        choreography,
        composition,
        motion,
        _text,
    ) = build_handoff_case(tmp_path)
    cue_index = next(index for index, cue in enumerate(motion) if cue.segments)
    cue = motion[cue_index]
    segment = cue.segments[0]

    exact = segment.model_copy(update={"handoff_deadline": segment.end})
    exact_cue = cue.model_copy(update={"segments": [exact, *cue.segments[1:]]})
    exact_motion = list(motion)
    exact_motion[cue_index] = exact_cue
    LayerHandoffValidator.require_motion_for_text_and_render(
        story=story,
        assets=assets,
        composition=composition,
        choreography=choreography,
        motion=exact_motion,
    )

    late = segment.model_copy(update={"handoff_deadline": segment.end - 0.01})
    late_cue = cue.model_copy(update={"segments": [late, *cue.segments[1:]]})
    broken = list(motion)
    broken[cue_index] = late_cue
    error = expect_handoff_failure(
        "MOTION_HANDOFF_CONTRACT_VIOLATIONS",
        lambda: LayerHandoffValidator.require_motion_for_text_and_render(
            story=story,
            assets=assets,
            composition=composition,
            choreography=choreography,
            motion=broken,
        ),
    )
    assert any(
        row["kind"] == "motion_segment_past_handoff_deadline"
        for row in error.details["violations"]
    )

def test_motion_handoff_allows_static_composition_item_without_motion(tmp_path: Path) -> None:
    (
        _package,
        _transcript,
        assets,
        story,
        choreography,
        composition,
        motion,
        _text,
    ) = build_handoff_case(tmp_path)
    victim = next(cue for cue in motion if cue.beat_id == story[0].id)
    static_assets = [
        asset.model_copy(update={"can_animate_independently": False})
        if asset.id == victim.asset_id
        else asset
        for asset in assets
    ]
    reduced_motion = [cue for cue in motion if cue is not victim]

    LayerHandoffValidator.require_composition_for_motion(
        story=story, assets=static_assets, composition=composition
    )
    LayerHandoffValidator.require_motion_for_text_and_render(
        story=story,
        assets=static_assets,
        composition=composition,
        choreography=choreography,
        motion=reduced_motion,
    )

def test_motion_handoff_rejects_story_event_missing_from_choreography(tmp_path: Path) -> None:
    (
        _package,
        _transcript,
        assets,
        story,
        choreography,
        composition,
        motion,
        _text,
    ) = build_handoff_case(tmp_path)
    cue = next(cue for cue in motion if any(segment.semantic_event_id for segment in cue.segments))
    event_id = next(segment.semantic_event_id for segment in cue.segments if segment.semantic_event_id)
    directive_index = next(
        index for index, directive in enumerate(choreography.directives)
        if directive.beat_id == cue.beat_id
    )
    directive = choreography.directives[directive_index]
    assert any(flow.event_id == event_id for flow in directive.event_flows)
    directives = list(choreography.directives)
    directives[directive_index] = replace(
        directive,
        event_flows=tuple(flow for flow in directive.event_flows if flow.event_id != event_id),
    )
    broken_choreography = replace(choreography, directives=tuple(directives))

    error = expect_handoff_failure(
        "MOTION_HANDOFF_CONTRACT_VIOLATIONS",
        lambda: LayerHandoffValidator.require_motion_for_text_and_render(
            story=story,
            assets=assets,
            composition=composition,
            choreography=broken_choreography,
            motion=motion,
        ),
    )
    assert any(
        row["kind"] == "motion_segment_event_not_owned_by_choreography"
        and row["event_id"] == event_id
        for row in error.details["violations"]
    )

def test_motion_handoff_rejects_segment_participant_missing_from_composition(tmp_path: Path) -> None:
    (
        _package,
        _transcript,
        assets,
        story,
        choreography,
        composition,
        motion,
        _text,
    ) = build_handoff_case(tmp_path)
    cue_index = next(index for index, cue in enumerate(motion) if cue.segments)
    cue = motion[cue_index]
    beat = next(beat for beat in story if beat.id == cue.beat_id)
    source_asset = next(asset for asset in assets if asset.scene_id == beat.scene_id)
    synthetic = source_asset.model_copy(update={"id": f"{source_asset.id}-NOT-IN-LAYOUT"})
    segment = cue.segments[0].model_copy(update={"target_asset_id": synthetic.id})
    broken_motion = list(motion)
    broken_motion[cue_index] = cue.model_copy(
        update={"segments": [segment, *cue.segments[1:]]}
    )

    error = expect_handoff_failure(
        "MOTION_HANDOFF_CONTRACT_VIOLATIONS",
        lambda: LayerHandoffValidator.require_motion_for_text_and_render(
            story=story,
            assets=[*assets, synthetic],
            composition=composition,
            choreography=choreography,
            motion=broken_motion,
        ),
    )
    assert any(
        row["kind"] == "motion_segment_asset_missing_from_composition"
        and row["asset_id"] == synthetic.id
        for row in error.details["violations"]
    )

def test_motion_handoff_rejects_nonzero_entry_below_encoded_floor(tmp_path: Path) -> None:
    (
        _package,
        _transcript,
        assets,
        story,
        choreography,
        composition,
        motion,
        _text,
    ) = build_handoff_case(tmp_path)
    cue_index = next(
        index for index, cue in enumerate(motion)
        if not cue.params.get("render_constraints", {}).get("geometry_lock")
    )
    cue = motion[cue_index]
    params = dict(cue.params)
    program = dict(params["program"])
    keyframes = [dict(frame) for frame in program["keyframes"]]
    # Reproduce the production diagnostic class: metadata claims ~1.33 px ENTRY
    # on the canonical 1920-wide render, which is too small to survive encoding.
    tiny_dx = 1.33 / 1920.0
    for index, frame in enumerate(keyframes):
        if index == len(keyframes) - 1:
            frame.update(dx=0.0, dy=0.0, scale=1.0)
        else:
            frame.update(dx=tiny_dx, dy=0.0, scale=1.0)
    program["keyframes"] = keyframes
    params["program"] = program
    broken = list(motion)
    broken[cue_index] = cue.model_copy(update={"params": params})

    error = expect_handoff_failure(
        "MOTION_HANDOFF_CONTRACT_VIOLATIONS",
        lambda: LayerHandoffValidator.require_motion_for_text_and_render(
            story=story,
            assets=assets,
            composition=composition,
            choreography=choreography,
            motion=broken,
        ),
    )
    row = next(
        row for row in error.details["violations"]
        if row["kind"] == "motion_cue_entry_render_dead_zone"
    )
    assert row["expected_px"] == pytest.approx(1.33, abs=0.03)
    assert row["renderability_floor_px"] > row["expected_px"]


def test_motion_handoff_rejects_main_program_geometry_drift(tmp_path: Path) -> None:
    (
        _package,
        _transcript,
        assets,
        story,
        choreography,
        composition,
        motion,
        _text,
    ) = build_handoff_case(tmp_path)
    cue = motion[0]
    params = dict(cue.params)
    program = dict(params["program"])
    frames = [dict(frame) for frame in program["keyframes"]]
    frames[-1]["dx"] = 0.02
    program["keyframes"] = frames
    params["program"] = program
    broken = [cue.model_copy(update={"params": params}), *motion[1:]]

    error = expect_handoff_failure(
        "MOTION_HANDOFF_CONTRACT_VIOLATIONS",
        lambda: LayerHandoffValidator.require_motion_for_text_and_render(
            story=story,
            assets=assets,
            composition=composition,
            choreography=choreography,
            motion=broken,
        ),
    )
    assert any(
        row["kind"] == "motion_cue_does_not_restore_composition_identity"
        for row in error.details["violations"]
    )

