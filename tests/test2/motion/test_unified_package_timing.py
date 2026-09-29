from pathlib import Path
# Owner-scoped Test2 coverage; historical regression content is preserved.

from app.final_package import FinalPackageLoader
from app.models import Transcript, TranscriptWord, VisualAsset
from app.story.planner import StoryPlanner
from tests.support.unified_package import write_unified_package


def test_unified_package_drives_scene_ids_and_narration_timing(tmp_path: Path) -> None:
    script = "alpha beta gamma delta"
    package = write_unified_package(
        tmp_path / "package", script=script, package_id="timing-v2",
        scenes=[
            {
                "scene_id": "SCENE_001", "order": 0,
                "script_span": {"text": "alpha beta", "global_char_start": 0, "global_char_end": 10},
                "assets": [{
                    "asset_id": "a1", "script_text": "alpha beta",
                    "script_span": {"text": "alpha beta", "global_char_start": 0, "global_char_end": 10},
                    "appear_trigger": {"text": "alpha beta", "global_char_start": 0, "global_char_end": 10},
                    "binding_type": "EXPLICIT", "visual_focus": "PRIMARY",
                }],
                "visual_progression": [{
                    "action": "EXPLAIN", "targets": ["a1"],
                    "trigger": {"text": "alpha beta", "global_char_start": 0, "global_char_end": 10},
                }],
            },
            {
                "scene_id": "SCENE_002", "order": 1,
                "script_span": {"text": "gamma delta", "global_char_start": 11, "global_char_end": 22},
                "assets": [{
                    "asset_id": "a2", "script_text": "gamma delta",
                    "script_span": {"text": "gamma delta", "global_char_start": 11, "global_char_end": 22},
                    "appear_trigger": {"text": "gamma delta", "global_char_start": 11, "global_char_end": 22},
                    "binding_type": "EXPLICIT", "visual_focus": "PRIMARY",
                }],
                "visual_progression": [{
                    "action": "EXPLAIN", "targets": ["a2"],
                    "trigger": {"text": "gamma delta", "global_char_start": 11, "global_char_end": 22},
                }],
            },
        ],
    )
    model = FinalPackageLoader().load(package, tmp_path / "work")
    assert [scene.id for scene in model.scenes] == ["SCENE_001", "SCENE_002"]

    words = [
        TranscriptWord(start=0.20, end=0.55, text="alpha", char_start=0, char_end=5),
        TranscriptWord(start=0.60, end=0.95, text="beta", char_start=6, char_end=10),
        TranscriptWord(start=1.50, end=1.85, text="gamma", char_start=11, char_end=16),
        TranscriptWord(start=1.90, end=2.25, text="delta", char_start=17, char_end=22),
    ]
    transcript = Transcript(language="en", duration=2.5, segments=[], words=words)
    assets = [
        VisualAsset(id="a1", scene_id="SCENE_001", role="primary", image_path=package / "images" / "SCENE_001.png", extraction_method="test", source_area_ratio=0.4),
        VisualAsset(id="a2", scene_id="SCENE_002", role="primary", image_path=package / "images" / "SCENE_002.png", extraction_method="test", source_area_ratio=0.4),
    ]
    beats = StoryPlanner().plan(model, transcript, assets)
    assert len(beats) == 2
    assert beats[0].scene_id == "SCENE_001"
    assert beats[0].audio_start == 0.20
    assert beats[0].audio_end == 0.95
    assert beats[1].audio_start == 1.50
    assert beats[1].audio_end == 2.25
    assert 0.0 <= beats[0].start < beats[0].audio_start
    assert beats[0].end == beats[1].start
    assert beats[1].start < beats[1].audio_start
    # Reference-calibrated motion needs enough pre-roll to decelerate smoothly
    # into the spoken semantic anchor instead of snapping in the final 0.2s.
    assert beats[1].audio_start - beats[1].start >= 0.35
    assert beats[1].end == transcript.duration


def test_primary_motion_settles_on_audio_anchor() -> None:
    from app.models import CompositionBeat, LayoutItem, StoryBeat
    from app.motion.planner import MotionPlanner

    beat = StoryBeat(
        id="beat-001",
        scene_id="SCENE_001",
        start=0.86,
        end=2.0,
        audio_start=1.0,
        audio_end=1.8,
        narration="test",
        primary_asset_ids=["a1"],
        action="INTRODUCE",
    )
    composition = [CompositionBeat(
        beat_id=beat.id,
        items=[LayoutItem(asset_id="a1", x=0.5, y=0.5, width=0.5, height=0.5)],
    )]

    cue = MotionPlanner().plan([beat], composition)[0]

    assert cue.start <= beat.audio_start
    assert cue.end <= beat.audio_start + 0.05
    assert cue.start >= beat.start


def test_support_motion_reveals_sequentially_during_spoken_window() -> None:
    from app.models import CompositionBeat, LayoutItem, StoryBeat
    from app.motion.planner import MotionPlanner

    beat = StoryBeat(
        id="beat-001",
        scene_id="SCENE_001",
        start=0.70,
        end=3.0,
        audio_start=1.0,
        audio_end=2.6,
        narration="test",
        primary_asset_ids=["a1"],
        support_asset_ids=["a2", "a3", "a4", "a5"],
        action="INTRODUCE",
    )
    composition = [CompositionBeat(
        beat_id=beat.id,
        items=[
            LayoutItem(asset_id=f"a{index}", x=0.5, y=0.5, width=0.4, height=0.4)
            for index in range(1, 6)
        ],
    )]

    cues = MotionPlanner().plan([beat], composition)
    supports = cues[1:]

    assert len(supports) == 4
    assert all(beat.start <= cue.start < cue.end <= beat.end for cue in supports)
    assert supports[0].start >= beat.audio_start
    assert supports[-1].end <= beat.audio_end

    starts = [cue.start for cue in supports]
    assert starts == sorted(starts)
    gaps = [later - earlier for earlier, later in zip(starts, starts[1:])]
    assert all(0.15 <= gap <= 0.39 for gap in gaps)
