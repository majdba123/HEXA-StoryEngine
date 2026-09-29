from __future__ import annotations

from pathlib import Path

import pytest

from app.canonical import (
    CanonicalAsset,
    CanonicalPackage,
    CanonicalScene,
    CanonicalScriptSpan,
    CanonicalSemanticEvent,
)
from app.models import StoryBeat, StorySemanticContext, Transcript, TranscriptWord, VisualAsset
from app.shared.errors import StageFailedError
from app.story.activation import SemanticActivationPlanner
from app.story.planner import StoryPlanner
from app.story.windows import StoryAssetActivation


def _event(event_id: str, order: int, start: int, end: int) -> CanonicalSemanticEvent:
    text = "alpha beta gamma"[start:end]
    return CanonicalSemanticEvent(
        semantic_event_id=event_id,
        scene_id="SCENE_001",
        script_text=text,
        script_span=CanonicalScriptSpan(
            text=text,
            global_char_start=start,
            global_char_end=end,
        ),
        sequence_order=order,
        visual_leader_asset_id="A",
        participant_asset_ids=("A",),
    )


def _package(*, events: tuple[CanonicalSemanticEvent, ...]) -> CanonicalPackage:
    scene = CanonicalScene(
        id="SCENE_001",
        image_path=Path("scene.png"),
        order=0,
        script_char_start=0,
        script_char_end=15,
        units=(
            CanonicalAsset(
                unit_id="A",
                asset_id="A",
                scene_id="SCENE_001",
                script_text="alpha",
                script_span=CanonicalScriptSpan(
                    text="alpha",
                    global_char_start=0,
                    global_char_end=5,
                ),
                semantic_event_id="E1",
            ),
        ),
        semantic_events=events,
    )
    return CanonicalPackage(
        root=Path("."),
        package_id="test2-story",
        script="alpha beta gamma",
        scenes=(scene,),
        has_authoritative_semantics=True,
    )


def _carrier_window() -> StoryAssetActivation:
    return StoryAssetActivation(
        asset_id="cutout-A",
        semantic_unit_id="A",
        trigger_text="alpha",
        trigger_char_start=0,
        trigger_char_end=5,
        spoken_start=0.10,
        spoken_end=0.35,
        confidence=1.0,
        source="unified_final_package",
        policy="EXPLICIT",
        semantic_event_id="E1",
        semantic_event_order=1,
        semantic_event_roles=["LEADER"],
        phrase_start=0.10,
        phrase_end=0.35,
        reveal_start=0.10,
        semantic_peak=0.22,
        settle_at=0.32,
        activation_policy="OWN_WINDOW",
    )


def test_story_reuses_proven_carrier_for_later_authored_event() -> None:
    package = _package(events=(
        _event("E1", 1, 0, 5),
        _event("E2", 2, 6, 10),
    ))
    scene = package.scenes[0]
    beat = StoryBeat(
        id="beat-001",
        scene_id=scene.id,
        start=0.0,
        end=1.2,
        audio_start=0.0,
        audio_end=1.2,
        narration="alpha beta",
        primary_asset_ids=["cutout-A"],
        support_asset_ids=[],
        action="INTRODUCE",
    )
    transcript = Transcript(
        duration=1.2,
        segments=[],
        words=[
            TranscriptWord(start=0.10, end=0.35, text="alpha", char_start=0, char_end=5),
            TranscriptWord(start=0.55, end=0.80, text="beta", char_start=6, char_end=10),
        ],
        timing_source="forced_alignment",
    )
    visual = VisualAsset(
        id="cutout-A",
        scene_id=scene.id,
        role="primary",
        image_path=Path("cutout.png"),
        extraction_method="test2",
    )

    proxies = SemanticActivationPlanner()._reused_semantic_event_proxies(
        package=package,
        transcript=transcript,
        scene=scene,
        beat=beat,
        assets=[visual],
        windows=[_carrier_window()],
        existing_proxies=[],
    )

    assert len(proxies) == 1
    assert proxies[0].semantic_event_id == "E2"
    assert proxies[0].asset_id == "cutout-A"
    assert proxies[0].semantic_unit_id == "A"
    assert proxies[0].authority == "FINAL_PACKAGE_REUSED_CARRIER_PROXY"
    assert proxies[0].spoken_start == pytest.approx(0.55)


def test_story_contract_rejects_missing_semantic_metadata() -> None:
    package = _package(events=(_event("E1", 1, 0, 5),))
    visual = VisualAsset(
        id="cutout-A",
        scene_id="SCENE_001",
        role="primary",
        image_path=Path("cutout.png"),
        extraction_method="test2",
    )
    beat = StoryBeat(
        id="beat-001",
        scene_id="SCENE_001",
        start=0.0,
        end=1.0,
        narration="alpha",
        primary_asset_ids=["cutout-A"],
        action="INTRODUCE",
    )

    with pytest.raises(StageFailedError) as exc:
        StoryPlanner._require_quality_contract(package=package, assets=[visual], beats=[beat])

    assert exc.value.effective_code == "FINAL_PACKAGE_METADATA_COVERAGE"


def test_story_contract_rejects_dropped_independent_asset() -> None:
    package = _package(events=())
    visual = VisualAsset(
        id="cutout-A",
        scene_id="SCENE_001",
        role="primary",
        image_path=Path("cutout.png"),
        extraction_method="test2",
    )
    beat = StoryBeat(
        id="beat-001",
        scene_id="SCENE_001",
        start=0.0,
        end=1.0,
        narration="alpha",
        primary_asset_ids=[],
        support_asset_ids=[],
        action="INTRODUCE",
        semantic_context=StorySemanticContext(),
    )

    with pytest.raises(StageFailedError) as exc:
        StoryPlanner._require_quality_contract(package=package, assets=[visual], beats=[beat])

    assert exc.value.effective_code == "ASSET_REACHES_STORY"


def test_story_uses_exact_visual_identity_as_proxy_without_promoting_ambiguous_binding() -> None:
    event = _event("E1", 1, 0, 5)
    package = _package(events=(event,))
    scene = package.scenes[0]
    # No trusted semantic window: the visual identity itself is exact, but semantic
    # activation remains conservative.  The event is represented through a proxy.
    abstention = StoryAssetActivation(
        asset_id="A",
        semantic_unit_id="A",
        confidence=0.0,
        source="semantic_abstention",
        policy="FALLBACK",
        evidence=["SAFE_ABSTENTION"],
        activation_policy="SAFE_ABSTENTION",
    )
    transcript = Transcript(
        duration=1.0,
        segments=[],
        words=[
            TranscriptWord(start=0.10, end=0.35, text="alpha", char_start=0, char_end=5),
        ],
        timing_source="forced_alignment",
    )
    visual = VisualAsset(
        id="A",
        scene_id=scene.id,
        role="primary",
        image_path=Path("compound.png"),
        extraction_method="test2",
        can_animate_independently=False,
        compound=True,
    )
    beat = StoryBeat(
        id="beat-001",
        scene_id=scene.id,
        start=0.0,
        end=0.9,
        audio_start=0.0,
        audio_end=0.9,
        narration="alpha",
        primary_asset_ids=["A"],
        action="INTRODUCE",
    )

    proxies = SemanticActivationPlanner()._reused_semantic_event_proxies(
        package=package,
        transcript=transcript,
        scene=scene,
        beat=beat,
        assets=[visual],
        windows=[abstention],
        existing_proxies=[],
    )

    assert len(proxies) == 1
    assert proxies[0].asset_id == "A"
    assert proxies[0].semantic_event_id == "E1"
    assert "carrier_proof=explicit_real_asset_id" in proxies[0].evidence

