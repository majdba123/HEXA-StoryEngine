from __future__ import annotations

from pathlib import Path

import pytest

from app.models import (
    AssetActivation,
    CompositionBeat,
    LayoutItem,
    StoryBeat,
    VisualAsset,
)
from app.motion import MotionPlanner
from app.motion.order import MotionOrderResolver
from app.story.sync_qa import StorySyncQA
from app.story.windows import schedule_windows


def _activation(
    asset_id: str,
    *,
    order: int,
    unit: str | None = None,
    group_policy: str = "SEQUENTIAL_WITHIN_PHRASE",
    multi: bool = False,
) -> AssetActivation:
    evidence = ["visual_identity_multi_cutout_member"] if multi else []
    return AssetActivation(
        asset_id=asset_id,
        semantic_unit_id=unit or asset_id,
        trigger_text="alpha beta gamma",
        trigger_char_start=0,
        trigger_char_end=16,
        spoken_start=0.20,
        spoken_end=1.40,
        confidence=0.98,
        source="final_package_semantic_binding",
        policy="EXPLICIT",
        semantic_group_id="g",
        sequence_order=order,
        binding_type="EXPLICIT",
        group_animation_policy=group_policy,
        evidence=evidence,
    )


def _beat(rows: list[AssetActivation]) -> StoryBeat:
    beat = StoryBeat(
        id="b",
        scene_id="s",
        start=0.0,
        end=1.6,
        audio_start=0.20,
        audio_end=1.40,
        narration="alpha beta gamma",
        primary_asset_ids=[],
        support_asset_ids=[row.asset_id for row in rows],
        action="INTRODUCE",
    )
    beat.asset_activations = schedule_windows(rows, beat, 1.6, set())
    return beat


def _settle(cue) -> float:
    return cue.start + max(0.05, cue.end - cue.start) * (
        cue.params["program"]["settle_progress"]
    )


def test_final_package_sequence_order_overrides_reversed_layout_order() -> None:
    rows = [
        _activation("one", order=1),
        _activation("two", order=2),
        _activation("three", order=3),
    ]
    beat = _beat(rows)
    layout = CompositionBeat(
        beat_id=beat.id,
        items=[
            LayoutItem(
                asset_id="three", x=0.75, y=0.5, width=0.18, height=0.18
            ),
            LayoutItem(
                asset_id="two", x=0.50, y=0.5, width=0.18, height=0.18
            ),
            LayoutItem(
                asset_id="one", x=0.25, y=0.5, width=0.18, height=0.18
            ),
        ],
    )

    cues = MotionPlanner().plan([beat], [layout])

    assert [cue.asset_id for cue in cues] == ["one", "two", "three"]
    assert [
        cue.params["motion_order"]["sequence_order"] for cue in cues
    ] == [1, 2, 3]
    assert cues[0].start < cues[1].start < cues[2].start
    assert all(
        cue.params["motion_order"]["source"].startswith(
            "final_package_sequence_order"
        )
        for cue in cues
    )
    assert StorySyncQA().inspect(story=[beat], motion=cues).passed


def test_locator_multi_cutout_unit_gets_internal_geometry_flow_order() -> None:
    rows = [
        _activation("previous", order=1, unit="previous"),
        _activation("card-c", order=2, unit="cards", multi=True),
        _activation("card-b", order=2, unit="cards", multi=True),
        _activation("card-a", order=2, unit="cards", multi=True),
        _activation("next", order=3, unit="next"),
    ]
    beat = _beat(rows)
    layout = CompositionBeat(
        beat_id=beat.id,
        items=[
            LayoutItem(
                asset_id="next", x=0.92, y=0.5, width=0.12, height=0.12
            ),
            LayoutItem(
                asset_id="card-c", x=0.72, y=0.5, width=0.15, height=0.15
            ),
            LayoutItem(
                asset_id="card-b", x=0.52, y=0.5, width=0.15, height=0.15
            ),
            LayoutItem(
                asset_id="card-a", x=0.32, y=0.5, width=0.15, height=0.15
            ),
            LayoutItem(
                asset_id="previous", x=0.10, y=0.5, width=0.12, height=0.12
            ),
        ],
    )

    cues = MotionPlanner().plan([beat], [layout])
    card_cues = [
        cue for cue in cues if cue.asset_id.startswith("card-")
    ]

    assert [cue.asset_id for cue in card_cues] == [
        "card-a",
        "card-b",
        "card-c",
    ]
    assert [
        cue.params["motion_order"]["internal_index"] for cue in card_cues
    ] == [0, 1, 2]
    assert all(
        cue.params["motion_order"]["internal_count"] == 3
        for cue in card_cues
    )
    assert all(
        cue.params["motion_order"]["stagger_applied"]
        for cue in card_cues
    )
    assert card_cues[0].start < card_cues[1].start < card_cues[2].start

    story_windows = [
        row
        for row in beat.asset_activations
        if row.semantic_unit_id == "cards"
    ]
    story_start = min(row.reveal_start for row in story_windows)
    story_end = max(row.settle_at for row in story_windows)
    assert card_cues[0].start == pytest.approx(story_start)
    assert _settle(card_cues[-1]) == pytest.approx(story_end)
    assert all(
        story_start <= cue.start < cue.end <= story_end
        for cue in card_cues
    )
    assert StorySyncQA().inspect(story=[beat], motion=cues).passed


def test_same_position_multi_cutout_falls_back_to_small_to_large_visual_size() -> None:
    rows = [
        _activation("large", order=1, unit="unit", multi=True),
        _activation("small", order=1, unit="unit", multi=True),
        _activation("medium", order=1, unit="unit", multi=True),
    ]
    beat = _beat(rows)
    items = [
        LayoutItem(
            asset_id="large", x=0.5, y=0.5, width=0.30, height=0.30
        ),
        LayoutItem(
            asset_id="small", x=0.5, y=0.5, width=0.10, height=0.10
        ),
        LayoutItem(
            asset_id="medium", x=0.5, y=0.5, width=0.20, height=0.20
        ),
    ]

    ordered = MotionOrderResolver().resolve(beat=beat, items=items)

    assert [slot.item.asset_id for slot in ordered] == [
        "small",
        "medium",
        "large",
    ]
    assert [slot.internal_index for slot in ordered] == [0, 1, 2]


def test_simultaneous_visual_unit_is_not_internally_staggered() -> None:
    rows = [
        _activation(
            "left",
            order=1,
            unit="pair",
            group_policy="SIMULTANEOUS_VISUAL_UNIT",
            multi=True,
        ),
        _activation(
            "right",
            order=1,
            unit="pair",
            group_policy="SIMULTANEOUS_VISUAL_UNIT",
            multi=True,
        ),
    ]
    beat = _beat(rows)
    layout = CompositionBeat(
        beat_id=beat.id,
        items=[
            LayoutItem(
                asset_id="right", x=0.7, y=0.5, width=0.2, height=0.2
            ),
            LayoutItem(
                asset_id="left", x=0.3, y=0.5, width=0.2, height=0.2
            ),
        ],
    )

    cues = MotionPlanner().plan([beat], [layout])

    assert [cue.asset_id for cue in cues] == ["right", "left"]
    assert cues[0].start == pytest.approx(cues[1].start)
    assert all(
        cue.params["motion_order"]["internal_count"] == 1
        for cue in cues
    )
    assert all(
        not cue.params["motion_order"]["stagger_applied"]
        for cue in cues
    )


def test_pass2_family_members_are_not_split_by_internal_ordering(
    tmp_path: Path,
) -> None:
    rows = [
        _activation("family", order=1, unit="compound", multi=True),
        _activation(
            "family:secondary-01",
            order=1,
            unit="compound",
            multi=True,
        ),
    ]
    beat = _beat(rows)
    layout = CompositionBeat(
        beat_id=beat.id,
        items=[
            LayoutItem(
                asset_id="family:secondary-01",
                x=0.5,
                y=0.5,
                width=0.5,
                height=0.5,
            ),
            LayoutItem(
                asset_id="family",
                x=0.5,
                y=0.5,
                width=0.5,
                height=0.5,
            ),
        ],
    )
    assets = [
        VisualAsset(
            id="family",
            scene_id="s",
            role="primary",
            image_path=tmp_path / "family.png",
            extraction_method="test+pass2_main",
            asset_family_id="family",
            render_as_family_canvas=True,
        ),
        VisualAsset(
            id="family:secondary-01",
            scene_id="s",
            role="secondary_object",
            image_path=tmp_path / "family-secondary.png",
            extraction_method="test+pass2_secondary",
            parent_asset_id="family",
            asset_family_id="family",
            render_as_family_canvas=True,
        ),
    ]

    cues = MotionPlanner().plan(
        [beat],
        [layout],
        assets=assets,
    )

    assert [cue.asset_id for cue in cues] == [
        "family:secondary-01",
        "family",
    ]
    assert cues[0].start == pytest.approx(cues[1].start)
    assert all(
        cue.params["motion_order"]["internal_count"] == 1
        for cue in cues
    )
    assert all(
        not cue.params["motion_order"]["stagger_applied"]
        for cue in cues
    )
