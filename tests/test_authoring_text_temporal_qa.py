from __future__ import annotations

from app.models import (
    CompositionBeat,
    StoryBeat,
    TextCompositionBeat,
    TextCue,
    TextLayoutItem,
    TextPlan,
    Transcript,
)
from app.qa.authoring import AuthoringVisualQA


def _beat() -> StoryBeat:
    return StoryBeat(
        id="beat-001",
        scene_id="scene-001",
        start=0.0,
        end=2.0,
        audio_start=0.0,
        audio_end=2.0,
        narration="generic narration",
        action="INTRODUCE",
    )


def _cue(cue_id: str, *, start: float, end: float) -> TextCue:
    return TextCue(
        id=cue_id,
        beat_id="beat-001",
        text=f"keyword {cue_id}",
        semantic_type="keyword",
        source_char_start=0,
        source_char_end=4,
        spoken_start=start,
        spoken_end=end,
        emphasis_time=start,
        priority=60,
        style_id="keyword",
    )


def _layout(*cue_ids: str) -> list[TextCompositionBeat]:
    return [
        TextCompositionBeat(
            beat_id="beat-001",
            items=[
                TextLayoutItem(
                    text_cue_id=cue_id,
                    x=0.50,
                    y=0.15,
                    max_width=0.30,
                    font_scale=1.0,
                    z=50,
                    placement="top",
                )
                for cue_id in cue_ids
            ],
        )
    ]


def _inspect(cues: list[TextCue]):
    beat = _beat()
    return AuthoringVisualQA().inspect(
        transcript=Transcript(
            language="en",
            duration=2.0,
            segments=[],
            words=[],
            timing_source="forced_alignment",
        ),
        composition=[CompositionBeat(beat_id=beat.id, items=[])],
        motion=[],
        story=[beat],
        text=TextPlan(cues=cues, styles=[]),
        text_composition=_layout(*(cue.id for cue in cues)),
        assets=[],
    )


def test_same_text_slot_is_reusable_when_visibility_windows_do_not_overlap() -> None:
    report = _inspect([
        _cue("text-a", start=0.00, end=0.30),
        _cue("text-b", start=1.00, end=1.30),
    ])

    assert report.text_layout_violations == ()


def test_same_text_slot_still_fails_when_visibility_windows_overlap() -> None:
    report = _inspect([
        _cue("text-a", start=0.00, end=0.55),
        _cue("text-b", start=0.02, end=0.60),
    ])

    assert len(report.text_layout_violations) == 1
    violation = report.text_layout_violations[0]
    assert "text_text_overlap:text-a:text-b" in violation
    assert ":time=" in violation

def test_later_visual_does_not_fail_text_overlap_before_visual_reveal() -> None:
    from pathlib import Path

    from app.models import LayoutItem, MotionCue, VisualAsset

    beat = _beat()
    cue = _cue("text-a", start=0.10, end=0.30)
    text = TextPlan(cues=[cue], styles=[])
    visual = CompositionBeat(
        beat_id=beat.id,
        items=[
            LayoutItem(
                asset_id="context",
                x=0.15,
                y=0.75,
                width=0.18,
                height=0.18,
            ),
            LayoutItem(
                asset_id="future",
                x=0.50,
                y=0.15,
                width=0.36,
                height=0.22,
            ),
        ],
    )
    assets = [
        VisualAsset(
            id="context",
            scene_id=beat.scene_id,
            role="visual",
            image_path=Path("/missing/context.png"),
            extraction_method="test",
        ),
        VisualAsset(
            id="future",
            scene_id=beat.scene_id,
            role="visual",
            image_path=Path("/missing/future.png"),
            extraction_method="test",
        ),
    ]
    motion = [
        MotionCue(
            beat_id=beat.id,
            asset_id="context",
            kind="program_v3",
            start=0.0,
            end=0.25,
            params={},
        ),
        MotionCue(
            beat_id=beat.id,
            asset_id="future",
            kind="program_v3",
            start=1.80,
            end=1.95,
            params={},
        ),
    ]
    report = AuthoringVisualQA().inspect(
        transcript=Transcript(
            language="en",
            duration=2.0,
            segments=[],
            words=[],
            timing_source="forced_alignment",
        ),
        composition=[visual],
        motion=motion,
        story=[beat],
        text=text,
        text_composition=_layout(cue.id),
        assets=assets,
    )

    assert report.text_layout_violations == ()


def test_visual_that_reveals_during_text_visibility_still_fails_overlap() -> None:
    from pathlib import Path

    from app.models import LayoutItem, MotionCue, VisualAsset

    beat = _beat()
    cue = _cue("text-a", start=0.10, end=0.30)
    text = TextPlan(cues=[cue], styles=[])
    visual = CompositionBeat(
        beat_id=beat.id,
        items=[
            LayoutItem(
                asset_id="current",
                x=0.50,
                y=0.15,
                width=0.36,
                height=0.22,
            ),
        ],
    )
    asset = VisualAsset(
        id="current",
        scene_id=beat.scene_id,
        role="visual",
        image_path=Path("/missing/current.png"),
        extraction_method="test",
    )
    motion = [
        MotionCue(
            beat_id=beat.id,
            asset_id="current",
            kind="program_v3",
            start=0.15,
            end=0.50,
            params={},
        ),
    ]
    report = AuthoringVisualQA().inspect(
        transcript=Transcript(
            language="en",
            duration=2.0,
            segments=[],
            words=[],
            timing_source="forced_alignment",
        ),
        composition=[visual],
        motion=motion,
        story=[beat],
        text=text,
        text_composition=_layout(cue.id),
        assets=[asset],
    )

    assert any(
        "text_visual_overlap:text-a" in row
        for row in report.text_layout_violations
    )
