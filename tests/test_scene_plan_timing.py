from pathlib import Path

from app.input.loader import FinalPackageLoader
from app.models import Transcript, TranscriptWord, VisualAsset
from app.story.planner import StoryPlanner


def test_scene_plan_drives_scene_ids_and_narration_timing(tmp_path: Path) -> None:
    package = tmp_path / "package"
    (package / "scenes").mkdir(parents=True)
    from PIL import Image
    Image.new("RGB", (320, 180), "white").save(package / "scenes" / "SCENE_001.png")
    Image.new("RGB", (320, 180), "white").save(package / "scenes" / "SCENE_002.png")
    script = "alpha beta gamma delta"
    (package / "canonical_script.txt").write_text(script, encoding="utf-8")
    (package / "manifest.json").write_text(
        '{"project_id":"p","scene_plan":"scene_plan.json","canonical_script":"canonical_script.txt"}',
        encoding="utf-8",
    )
    (package / "scene_plan.json").write_text(
        '''{"project_id":"p","scenes":[
          {"scene_id":"SCENE_001","order":1,"image":"scenes/SCENE_001.png","script_span":{"global_char_start":0,"global_char_end":9,"text":"alpha beta"},"visual_progression":[{"action":"EXPLAIN","trigger":{"global_char_start":0,"global_char_end":9},"targets":["U1"]}]},
          {"scene_id":"SCENE_002","order":2,"image":"scenes/SCENE_002.png","script_span":{"global_char_start":11,"global_char_end":21,"text":"gamma delta"},"visual_progression":[{"action":"EXPLAIN","trigger":{"global_char_start":11,"global_char_end":21},"targets":["U2"]}]}
        ]}''',
        encoding="utf-8",
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
        VisualAsset(id="a1", scene_id="SCENE_001", role="primary", image_path=package / "scenes" / "SCENE_001.png", extraction_method="test", source_area_ratio=0.4),
        VisualAsset(id="a2", scene_id="SCENE_002", role="primary", image_path=package / "scenes" / "SCENE_002.png", extraction_method="test", source_area_ratio=0.4),
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
