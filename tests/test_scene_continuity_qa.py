from __future__ import annotations

from app.models import CompositionBeat, LayoutItem, MotionCue, StoryBeat
from app.qa import SceneContinuityQA


def _layouts() -> list[CompositionBeat]:
    return [
        CompositionBeat(
            beat_id="a",
            items=[LayoutItem(asset_id="old", x=0.5, y=0.5, width=0.4, height=0.4)],
        ),
        CompositionBeat(
            beat_id="b",
            items=[LayoutItem(asset_id="new", x=0.5, y=0.5, width=0.4, height=0.4)],
        ),
    ]


def test_scene_continuity_qa_requires_cross_scene_bridge() -> None:
    story = [
        StoryBeat(
            id="a", scene_id="scene-a", start=0.0, end=1.0,
            narration="a", primary_asset_ids=["old"], action="INTRODUCE",
        ),
        StoryBeat(
            id="b", scene_id="scene-b", start=1.0, end=2.0,
            narration="b", primary_asset_ids=["new"], action="HANDOFF",
            handoff_from="old",
        ),
    ]
    motion = [
        MotionCue(beat_id="a", asset_id="old", kind="reveal_in", start=0.0, end=0.2),
        MotionCue(beat_id="b", asset_id="new", kind="handoff_in", start=1.0, end=1.2),
    ]

    report = SceneContinuityQA().inspect(
        story=story,
        composition=_layouts(),
        motion=motion,
    )

    assert report.ok, report.violations
    assert report.checked_boundaries == 1
    assert report.bridged_boundaries == 1
    assert report.blur_boundaries == 1


def test_scene_continuity_qa_rejects_incoming_before_story_boundary() -> None:
    story = [
        StoryBeat(
            id="a", scene_id="scene-a", start=0.0, end=1.0,
            narration="a", primary_asset_ids=["old"], action="INTRODUCE",
        ),
        StoryBeat(
            id="b", scene_id="scene-b", start=1.0, end=2.0,
            narration="b", primary_asset_ids=["new"], action="REVEAL_DETAIL",
            handoff_from="old",
        ),
    ]
    motion = [
        MotionCue(beat_id="a", asset_id="old", kind="reveal_in", start=0.0, end=0.2),
        MotionCue(beat_id="b", asset_id="new", kind="reveal_in", start=0.90, end=1.2),
    ]

    report = SceneContinuityQA().inspect(
        story=story,
        composition=_layouts(),
        motion=motion,
    )

    assert not report.ok
    assert any(row.code == "INCOMING_BEFORE_STORY" for row in report.violations)
