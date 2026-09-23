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
