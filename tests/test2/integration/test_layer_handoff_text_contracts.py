from __future__ import annotations

from pathlib import Path

from app.composition import TextCompositionPlanner
from app.motion import TextMotionPlanner
from app.shared.handoff import LayerHandoffValidator
from tests.test2.integration.handoff_contract_support import (
    build_handoff_case,
    expect_handoff_failure,
)


def test_text_handoff_rejects_cross_scene_anchor(tmp_path: Path) -> None:
    package, transcript, assets, story, _choreography, _composition, _motion, text = build_handoff_case(tmp_path)
    assert text.cues
    cue = text.cues[0]
    beat = next(row for row in story if row.id == cue.beat_id)
    foreign = next(asset for asset in assets if asset.scene_id != beat.scene_id)
    broken_cue = cue.model_copy(update={"anchor_asset_id": foreign.id})
    broken = text.model_copy(update={"cues": [broken_cue, *text.cues[1:]]})
    error = expect_handoff_failure(
        "TEXT_HANDOFF_CONTRACT_VIOLATIONS",
        lambda: LayerHandoffValidator.require_text_for_composition(
            transcript=transcript, story=story, assets=assets, text=broken
        ),
    )
    assert any(
        row["kind"] == "text_anchor_reference_cross_scene"
        for row in error.details["violations"]
    )

def test_text_render_handoff_rejects_dropped_text_motion(tmp_path: Path) -> None:
    (
        _package,
        _transcript,
        assets,
        story,
        choreography,
        composition,
        motion,
        text,
    ) = build_handoff_case(tmp_path)
    text_composition = TextCompositionPlanner().plan(
        story,
        composition,
        text.cues,
        assets,
        visual_motion=motion,
    )
    accepted = {
        item.text_cue_id for beat in text_composition for item in beat.items
    }
    text = text.model_copy(
        update={"cues": [cue for cue in text.cues if cue.id in accepted]}
    )
    text_motion = TextMotionPlanner().plan(
        story,
        text.cues,
        text_composition,
        choreography,
        visual_motion=motion,
    )
    assert text_motion
    broken = text_motion[1:]
    error = expect_handoff_failure(
        "TEXT_HANDOFF_CONTRACT_VIOLATIONS",
        lambda: LayerHandoffValidator.require_text_render_contract(
            story=story,
            assets=assets,
            text=text,
            text_composition=text_composition,
            text_motion=broken,
        ),
    )
    assert any(
        row["kind"] == "text_motion_coverage_mismatch"
        for row in error.details["violations"]
    )

def test_text_handoff_rejects_unknown_style(tmp_path: Path) -> None:
    package, transcript, assets, story, _choreography, _composition, _motion, text = build_handoff_case(tmp_path)
    assert text.cues
    broken_cue = text.cues[0].model_copy(update={"style_id": "MISSING_STYLE"})
    broken = text.model_copy(update={"cues": [broken_cue, *text.cues[1:]]})
    error = expect_handoff_failure(
        "TEXT_HANDOFF_CONTRACT_VIOLATIONS",
        lambda: LayerHandoffValidator.require_text_for_composition(
            transcript=transcript, story=story, assets=assets, text=broken
        ),
    )
    assert any(
        row["kind"] == "text_cue_unknown_style"
        for row in error.details["violations"]
    )

def test_text_handoff_rejects_emphasis_outside_cue(tmp_path: Path) -> None:
    _package, transcript, assets, story, _choreography, _composition, _motion, text = build_handoff_case(tmp_path)
    assert text.cues
    cue = text.cues[0]
    broken_cue = cue.model_copy(update={"emphasis_time": cue.spoken_end + 0.10})
    broken = text.model_copy(update={"cues": [broken_cue, *text.cues[1:]]})
    error = expect_handoff_failure(
        "TEXT_HANDOFF_CONTRACT_VIOLATIONS",
        lambda: LayerHandoffValidator.require_text_for_composition(
            transcript=transcript, story=story, assets=assets, text=broken
        ),
    )
    assert any(
        row["kind"] == "text_emphasis_outside_cue"
        for row in error.details["violations"]
    )

def test_text_handoff_rejects_token_character_span_outside_cue(tmp_path: Path) -> None:
    _package, transcript, assets, story, _choreography, _composition, _motion, text = build_handoff_case(tmp_path)
    cue_index = next(index for index, cue in enumerate(text.cues) if cue.tokens)
    cue = text.cues[cue_index]
    token = cue.tokens[0].model_copy(update={"source_char_end": cue.source_char_end + 5})
    broken_cue = cue.model_copy(update={"tokens": [token, *cue.tokens[1:]]})
    cues = list(text.cues)
    cues[cue_index] = broken_cue
    broken = text.model_copy(update={"cues": cues})
    error = expect_handoff_failure(
        "TEXT_HANDOFF_CONTRACT_VIOLATIONS",
        lambda: LayerHandoffValidator.require_text_for_composition(
            transcript=transcript, story=story, assets=assets, text=broken
        ),
    )
    assert any(
        row["kind"] == "text_token_char_span_outside_cue"
        for row in error.details["violations"]
    )

