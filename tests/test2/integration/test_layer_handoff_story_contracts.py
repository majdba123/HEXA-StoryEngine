from __future__ import annotations

from pathlib import Path

from app.shared.handoff import LayerHandoffValidator
from tests.test2.integration.handoff_contract_support import (
    build_handoff_case,
    expect_handoff_failure,
)


def test_asset_handoff_rejects_duplicate_runtime_identity(tmp_path: Path) -> None:
    package, _transcript, assets, *_ = build_handoff_case(tmp_path)
    expect_handoff_failure(
        "ASSET_HANDOFF_CONTRACT_VIOLATIONS",
        lambda: LayerHandoffValidator.require_assets_for_story(
            package=package, assets=[assets[0], assets[0], *assets[1:]]
        ),
    )

def test_asset_handoff_rejects_foreign_package_scene(tmp_path: Path) -> None:
    package_a, _t1, _a1, *_ = build_handoff_case(tmp_path / "a", namespace="PKGA")
    _package_b, _t2, assets_b, *_ = build_handoff_case(tmp_path / "b", namespace="PKGB")
    error = expect_handoff_failure(
        "ASSET_HANDOFF_CONTRACT_VIOLATIONS",
        lambda: LayerHandoffValidator.require_assets_for_story(
            package=package_a, assets=assets_b
        ),
    )
    assert any(
        row["kind"] == "foreign_asset_scene"
        for row in error.details["violations"]
    )

def test_story_handoff_rejects_cross_scene_asset(tmp_path: Path) -> None:
    package, transcript, assets, story, *_ = build_handoff_case(tmp_path)
    foreign = next(asset for asset in assets if asset.scene_id != story[0].scene_id)
    broken = list(story)
    broken[0] = broken[0].model_copy(update={"support_asset_ids": [foreign.id]})
    error = expect_handoff_failure(
        "STORY_HANDOFF_CONTRACT_VIOLATIONS",
        lambda: LayerHandoffValidator.require_story_for_choreography(
            package=package, transcript=transcript, assets=assets, story=broken
        ),
    )
    assert any("cross_scene" in row["kind"] for row in error.details["violations"])

def test_story_handoff_rejects_timing_past_transcript(tmp_path: Path) -> None:
    package, transcript, assets, story, *_ = build_handoff_case(tmp_path)
    broken = list(story)
    broken[-1] = broken[-1].model_copy(update={"end": transcript.duration + 0.25})
    error = expect_handoff_failure(
        "STORY_HANDOFF_CONTRACT_VIOLATIONS",
        lambda: LayerHandoffValidator.require_story_for_choreography(
            package=package, transcript=transcript, assets=assets, story=broken
        ),
    )
    assert any(
        row["kind"] == "story_window_outside_transcript"
        for row in error.details["violations"]
    )

def test_story_handoff_allows_narration_to_outlive_visual_beat(tmp_path: Path) -> None:
    package, transcript, assets, story, *_ = build_handoff_case(tmp_path)
    beat_index = next(
        index
        for index, beat in enumerate(story[:-1])
        if beat.end + 0.05 <= transcript.duration
    )
    beat = story[beat_index]
    audio_start = beat.audio_start if beat.audio_start is not None else beat.start
    broken = list(story)
    broken[beat_index] = beat.model_copy(
        update={
            "audio_start": audio_start,
            "audio_end": min(transcript.duration, beat.end + 0.05),
        }
    )
    LayerHandoffValidator.require_story_for_choreography(
        package=package, transcript=transcript, assets=assets, story=broken
    )

