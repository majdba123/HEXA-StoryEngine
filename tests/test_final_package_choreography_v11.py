from __future__ import annotations

from pathlib import Path

import pytest

from app.choreography import (
    ChoreographyDirector,
    ChoreographyPattern,
)
from app.models import (
    AssetActivation,
    CompositionBeat,
    LayoutItem,
    PackageModel,
    SceneSource,
    StoryBeat,
    StoryRelation,
    StorySemanticContext,
    VisualAsset,
)
from app.motion import MotionPlanner


def _asset(asset_id: str, area: float = 0.15) -> VisualAsset:
    return VisualAsset(
        id=asset_id,
        scene_id="scene-1",
        role="visual",
        image_path=Path(f"/{asset_id}.png"),
        extraction_method="test",
        source_area_ratio=area,
    )


def _beat(
    *,
    activations: list[AssetActivation],
    relations: list[StoryRelation] | None = None,
    result_ids: list[str] | None = None,
) -> StoryBeat:
    ids = [row.asset_id for row in activations]
    return StoryBeat(
        id="beat-1",
        scene_id="scene-1",
        start=0.0,
        end=2.4,
        audio_start=0.3,
        audio_end=2.0,
        narration="semantic visual story",
        primary_asset_ids=ids[:1],
        support_asset_ids=ids[1:],
        action="REVEAL_DETAIL",
        asset_activations=activations,
        semantic_context=StorySemanticContext(
            story_role="ACTION",
            relations=relations or [],
            result_unit_ids=result_ids or [],
        ),
    )


def _package(asset_ids: list[str]) -> PackageModel:
    return PackageModel(
        root=Path("/tmp"),
        package_id="p",
        script="semantic visual story",
        scenes=[
            SceneSource(
                id="scene-1",
                image_path=Path("/scene.png"),
                order=0,
                units=[
                    {
                        "unit_id": asset_id,
                        "asset_id": asset_id,
                        "type": "VISUAL_ASSET_INTENT",
                    }
                    for asset_id in asset_ids
                ],
            )
        ],
    )


def _activation(
    asset_id: str,
    order: int,
    *,
    focus: str | None = None,
    state: dict[str, str] | None = None,
) -> AssetActivation:
    return AssetActivation(
        asset_id=asset_id,
        semantic_unit_id=asset_id,
        trigger_text="semantic visual story",
        spoken_start=0.8,
        spoken_end=1.5,
        confidence=0.99,
        source="final_package_semantic_binding",
        policy="EXPLICIT",
        semantic_group_id="g",
        sequence_order=order,
        group_animation_policy="SEQUENTIAL_WITHIN_PHRASE",
        visual_focus=focus,
        visual_state=state,
    )


def test_explicit_final_package_state_selects_state_transform_and_wins_inference() -> None:
    activations = [
        _activation("subject", 1),
        _activation(
            "target",
            2,
            focus="RESULT",
            state={"before": "PRIVATE", "after": "EXPOSED"},
        ),
    ]
    relation = StoryRelation(
        source_unit_id="subject",
        target_unit_id="target",
        kind="REVEALS",
        authority="FINAL_PACKAGE_ASSET_RELATION",
        confidence=0.98,
        causal=True,
    )
    beat = _beat(activations=activations, relations=[relation])
    assets = [_asset("subject"), _asset("target")]
    directive = ChoreographyDirector().plan(
        _package(["subject", "target"]),
        [beat],
        assets,
    ).directives[0]

    assert directive.pattern == ChoreographyPattern.STATE_TRANSFORM
    authored = next(row for row in directive.state_transitions if row.asset_id == "target")
    assert authored.from_state == "PRIVATE"
    assert authored.to_state == "EXPOSED"
    assert authored.authority == "FINAL_PACKAGE_VISUAL_STATE"
    assert directive.primary_asset_id == "target"


def test_explicit_relation_selects_cause_effect_and_relation_specific_result() -> None:
    activations = [
        _activation("subject", 1),
        _activation("object", 2),
        _activation("result", 3),
    ]
    relation = StoryRelation(
        source_unit_id="subject",
        target_unit_id="object",
        result_unit_id="result",
        kind="REPORTS_TO",
        authority="FINAL_PACKAGE_ASSET_RELATION",
        confidence=0.98,
        causal=True,
    )
    beat = _beat(
        activations=activations,
        relations=[relation],
        result_ids=["result"],
    )
    assets = [_asset("subject"), _asset("object"), _asset("result")]
    directive = ChoreographyDirector().plan(
        _package(["subject", "object", "result"]),
        [beat],
        assets,
    ).directives[0]

    assert directive.pattern == ChoreographyPattern.CAUSE_EFFECT_CHAIN
    authored = next(
        row for row in directive.interactions
        if row.authority == "FINAL_PACKAGE_ASSET_RELATION"
    )
    assert authored.subject_asset_id == "subject"
    assert authored.object_asset_id == "object"
    assert authored.result_asset_id == "result"
    assert authored.executable


def test_ordered_group_without_richer_metadata_uses_progressive_build() -> None:
    activations = [
        _activation("a", 1),
        _activation("b", 2),
        _activation("c", 3),
    ]
    beat = _beat(activations=activations)
    assets = [_asset("a"), _asset("b"), _asset("c")]
    directive = ChoreographyDirector().plan(
        _package(["a", "b", "c"]),
        [beat],
        assets,
    ).directives[0]

    assert directive.pattern == ChoreographyPattern.PROGRESSIVE_BUILD


def test_pattern_motion_has_one_controlled_pre_settle_accent_then_freezes() -> None:
    activations = [
        _activation("subject", 1),
        _activation("object", 2),
        _activation("result", 3),
    ]
    relation = StoryRelation(
        source_unit_id="subject",
        target_unit_id="object",
        result_unit_id="result",
        kind="CREATES",
        authority="FINAL_PACKAGE_ASSET_RELATION",
        confidence=0.98,
        causal=True,
    )
    beat = _beat(
        activations=activations,
        relations=[relation],
        result_ids=["result"],
    )
    assets = [_asset("subject"), _asset("object"), _asset("result")]
    choreography = ChoreographyDirector().plan(
        _package(["subject", "object", "result"]),
        [beat],
        assets,
    )
    composition = [
        CompositionBeat(
            beat_id=beat.id,
            items=[
                LayoutItem(asset_id="subject", x=0.2, y=0.5, width=0.2, height=0.25),
                LayoutItem(asset_id="object", x=0.5, y=0.5, width=0.2, height=0.25),
                LayoutItem(asset_id="result", x=0.8, y=0.5, width=0.2, height=0.25),
            ],
        )
    ]

    cues = MotionPlanner().plan(
        [beat],
        composition,
        choreography,
        assets=assets,
    )

    assert cues
    assert all(
        cue.params["choreography"]["pattern"] == "CAUSE_EFFECT_CHAIN"
        for cue in cues
    )
    subject = next(cue for cue in cues if cue.asset_id == "subject")
    frames = subject.params["program"]["keyframes"]
    settle = subject.params["program"]["settle_progress"]
    assert len(frames) == 4
    assert any(
        frame["progress"] < settle
        and (abs(frame["dx"]) > 1e-6 or abs(frame["dy"]) > 1e-6 or abs(frame["scale"] - 1.0) > 1e-6)
        for frame in frames[1:-1]
    )
    assert all(
        frame["dx"] == pytest.approx(0.0)
        and frame["dy"] == pytest.approx(0.0)
        and frame["scale"] == pytest.approx(1.0)
        for frame in frames
        if frame["progress"] >= settle
    )
