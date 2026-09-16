import re
from pathlib import Path

from app.composition import TextCompositionPlanner
from app.models import (
    CompositionBeat,
    LayoutItem,
    StoryBeat,
    Transcript,
    TranscriptSegment,
    TranscriptWord,
    VisualAsset,
)
from app.motion import TextMotionPlanner
from app.text import TextPlanner


def _transcript(script: str, *, timing_source: str = "forced_alignment") -> Transcript:
    matches = list(re.finditer(r"\S+", script))
    words = [
        TranscriptWord(
            start=index * 0.45,
            end=index * 0.45 + 0.32,
            text=match.group(),
            char_start=match.start(),
            char_end=match.end(),
        )
        for index, match in enumerate(matches)
    ]
    return Transcript(
        language="ar",
        duration=max(1.0, words[-1].end + 0.3),
        segments=[
            TranscriptSegment(
                start=words[0].start,
                end=words[-1].end,
                text=script,
                char_start=0,
                char_end=len(script),
                words=words,
            )
        ],
        words=words,
        timing_source=timing_source,
    )


def _beat(transcript: Transcript) -> StoryBeat:
    return StoryBeat(
        id="beat-001",
        scene_id="scene-001",
        start=0.0,
        end=transcript.duration,
        audio_start=0.0,
        audio_end=transcript.words[-1].end,
        narration="الرصيد الظاهر 1000 ريال لكن 300 ريال محجوزة لعملية سابقة",
        primary_asset_ids=["wallet"],
        support_asset_ids=["lock"],
        action="EMPHASIZE",
    )


def _assets() -> list[VisualAsset]:
    return [
        VisualAsset(
            id="wallet",
            scene_id="scene-001",
            role="primary",
            image_path=Path("wallet.png"),
            extraction_method="fixture",
        ),
        VisualAsset(
            id="lock",
            scene_id="scene-001",
            role="support",
            image_path=Path("lock.png"),
            extraction_method="fixture",
        ),
    ]


def test_text_planner_selects_sparse_keywords_from_forced_alignment() -> None:
    script = "الرصيد الظاهر 1000 ريال لكن 300 ريال محجوزة لعملية سابقة"
    transcript = _transcript(script)
    beat = _beat(transcript)

    text = TextPlanner().plan(transcript=transcript, story=[beat], assets=_assets())

    assert [cue.text for cue in text.cues] == ["1000 ريال", "300 ريال محجوزة"]
    assert text.cues[0].semantic_type == "amount"
    assert text.cues[1].semantic_type == "warning_amount"
    assert all(cue.anchor_asset_id == "wallet" for cue in text.cues)
    assert all(cue.spoken_start >= 0 for cue in text.cues)
    assert [token.text for token in text.cues[0].tokens] == ["1000", "ريال"]
    assert [token.text for token in text.cues[1].tokens] == ["300", "ريال", "محجوزة"]
    assert all(token.spoken_end > token.spoken_start for cue in text.cues for token in cue.tokens)
    assert {style.id for style in text.styles} == {"amount", "warning_amount"}


def test_text_timing_refuses_non_forced_alignment_timestamps() -> None:
    script = "الرصيد الظاهر 1000 ريال"
    transcript = _transcript(script, timing_source="script_fallback")
    beat = _beat(transcript)

    text = TextPlanner().plan(transcript=transcript, story=[beat], assets=_assets())

    assert text.cues == []
    assert text.styles == []


def test_text_composition_is_separate_from_visual_composition() -> None:
    script = "الرصيد الظاهر 1000 ريال لكن 300 ريال محجوزة لعملية سابقة"
    transcript = _transcript(script)
    beat = _beat(transcript)
    text = TextPlanner().plan(transcript=transcript, story=[beat], assets=_assets())
    visual = [
        CompositionBeat(
            beat_id=beat.id,
            items=[
                LayoutItem(asset_id="wallet", x=0.50, y=0.55, width=0.44, height=0.52, z=20),
                LayoutItem(asset_id="lock", x=0.76, y=0.55, width=0.18, height=0.22, z=15),
            ],
        )
    ]

    text_composition = TextCompositionPlanner().plan([beat], visual, text.cues)

    assert len(text_composition) == 1
    assert len(text_composition[0].items) == 2
    assert all(item.text_cue_id.startswith("text-") for item in text_composition[0].items)
    assert visual[0].items[0].asset_id == "wallet"
    assert all(item.z >= 50 for item in text_composition[0].items)


def test_text_motion_is_separate_and_locked_to_spoken_start() -> None:
    script = "الرصيد الظاهر 1000 ريال لكن 300 ريال محجوزة لعملية سابقة"
    transcript = _transcript(script)
    beat = _beat(transcript)
    text = TextPlanner().plan(transcript=transcript, story=[beat], assets=_assets())
    visual = [
        CompositionBeat(
            beat_id=beat.id,
            items=[LayoutItem(asset_id="wallet", x=0.5, y=0.5, width=0.4, height=0.5, z=20)],
        )
    ]
    text_composition = TextCompositionPlanner().plan([beat], visual, text.cues)

    cues = TextMotionPlanner().plan([beat], text.cues, text_composition)

    assert len(cues) == len(text.cues)
    by_id = {cue.id: cue for cue in text.cues}
    for motion in cues:
        source = by_id[motion.text_cue_id]
        assert motion.start == source.spoken_start
        assert motion.params["emphasis_time"] == source.emphasis_time
        assert motion.params["anchor_asset_id"] == "wallet"
        assert motion.params["reveal_mode"] == "sequential_words"
        assert [token.text for token in motion.tokens] == [token.text for token in source.tokens]
        assert [token.start for token in motion.tokens] == [token.spoken_start for token in source.tokens]
