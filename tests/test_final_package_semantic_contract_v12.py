from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from PIL import Image

from app.choreography import ChoreographyDirector, ChoreographyPlan, ChoreographyPattern
from app.input.loader import FinalPackageLoader
from app.diagnostics.storytelling import StorytellingValidator
from app.models import (
    AssetActivation,
    CompositionBeat,
    LayoutItem,
    RenderPlan,
    StoryBeat,
    Transcript,
    TranscriptWord,
    VisualAsset,
)
from app.motion import MotionPlanner
from app.motion.order import MotionOrderResolver
from app.qa import MotionInteractionQA, RenderedMotionQA
from app.render.renderer import FFmpegRenderer
from app.story.planner import StoryPlanner
from app.story.windows import schedule_windows
from app.text.planner import TextPlanner
from app.text.semantic import KeywordCandidate


def _write_package(tmp_path: Path) -> Path:
    script = "alpha beta gamma"
    package = tmp_path / "package"
    (package / "scenes").mkdir(parents=True)
    Image.new("RGB", (320, 180), "white").save(package / "scenes" / "SCENE_001.png")
    (package / "canonical_script.txt").write_text(script, encoding="utf-8")

    assets = [
        {
            "scene_id": "SCENE_001", "asset_id": "a", "script_text": "alpha",
            "script_span": {"global_char_start": 0, "global_char_end": 5},
            "anchor_granularity": "EXACT_WORD", "binding_type": "EXPLICIT",
            "semantic_group_id": "G1", "sequence_order": 1, "confidence": 0.99,
            "semantic_role": "OBJECT", "visual_focus": "PRIMARY",
            "semantic_event_id": "E1", "compound_visual_classification": "SEPARABLE_SAFE",
        },
        {
            "scene_id": "SCENE_001", "asset_id": "b", "script_text": "beta",
            "script_span": {"global_char_start": 6, "global_char_end": 10},
            "anchor_granularity": "EXACT_WORD", "binding_type": "SEMANTIC",
            "semantic_group_id": "G1", "sequence_order": 2, "confidence": 0.96,
            "semantic_role": "ACTION", "visual_focus": "SUPPORT",
            "semantic_event_id": "E1", "compound_visual_classification": "SEPARABLE_SAFE",
        },
        {
            "scene_id": "SCENE_001", "asset_id": "c", "script_text": "gamma",
            "script_span": {"global_char_start": 11, "global_char_end": 16},
            "anchor_granularity": "EXACT_WORD", "binding_type": "EXPLICIT",
            "semantic_group_id": "G1", "sequence_order": 3, "confidence": 0.99,
            "semantic_role": "RESULT", "visual_focus": "RESULT",
            "semantic_event_id": "E2", "compound_visual_classification": "COMPOUND_REQUIRED",
            "internal_progression_unavailable": True,
        },
    ]
    events = [
        {
            "semantic_event_id": "E1", "scene_id": "SCENE_001",
            "script_text": "alpha beta",
            "script_span": {"global_char_start": 0, "global_char_end": 10},
            "anchor_granularity": "EXACT_PHRASE", "sequence_order": 1,
            "visual_leader_asset_id": "a", "participant_asset_ids": ["b"],
            "context_asset_ids": [], "result_asset_ids": [],
            "text_anchor_asset_id": "a", "confidence": 0.99, "depends_on_event_ids": [],
        },
        {
            "semantic_event_id": "E2", "scene_id": "SCENE_001",
            "script_text": "gamma",
            "script_span": {"global_char_start": 11, "global_char_end": 16},
            "anchor_granularity": "EXACT_WORD", "sequence_order": 2,
            "visual_leader_asset_id": "c", "participant_asset_ids": [],
            "context_asset_ids": [], "result_asset_ids": ["c"],
            "text_anchor_asset_id": "c", "confidence": 0.99, "depends_on_event_ids": ["E1"],
        },
    ]
    relations = [{
        "relation_id": "R1", "subject_asset_id": "a", "relation_type": "ENABLES",
        "object_asset_id": "b", "result_asset_id": "c",
        "script_text": script,
        "script_span": {"global_char_start": 0, "global_char_end": 16},
        "confidence": 0.97,
    }]
    scene = {
        "scene_id": "SCENE_001",
        "semantic_groups": [{
            "semantic_group_id": "G1", "script_text": script,
            "animation_policy": "SEQUENTIAL_WITHIN_PHRASE",
            "asset_ids": ["a", "b", "c"],
        }],
        "assets": assets,
        "relations": relations,
        "semantic_events": events,
        "progression": {"type": "GENERIC_PROGRESS", "event_order": ["E1", "E2"]},
    }

    (package / "manifest.json").write_text(json.dumps({
        "project_id": "v12-test", "package_version": "1.2",
        "scene_plan": "scene_plan.json", "canonical_script": "canonical_script.txt",
        "semantic_bindings": "semantic_bindings.json",
    }), encoding="utf-8")
    (package / "scene_plan.json").write_text(json.dumps({
        "project_id": "v12-test",
        "scenes": [{
            "scene_id": "SCENE_001", "order": 1, "image": "scenes/SCENE_001.png",
            "script_span": {"global_char_start": 0, "global_char_end": 16, "text": script},
            "units": [
                {"unit_id": row["asset_id"], "asset_id": row["asset_id"],
                 "type": "VISUAL_ASSET_INTENT", "role": row["semantic_role"]}
                for row in assets
            ],
            "semantic_events": events, "relations": relations,
            "progression": scene["progression"],
        }],
    }), encoding="utf-8")
    (package / "semantic_bindings.json").write_text(json.dumps({
        "schema_name": "HEXA_ASSET_LEVEL_SEMANTIC_BINDINGS",
        "schema_version": "1.2",
        "asset_is_semantic_intent_not_cutout": True,
        "cutout_mapping_cardinality": "ZERO_OR_ONE_OR_MANY",
        "no_fixed_timing": True,
        "scenes": [scene],
        "semantic_events": events,
    }), encoding="utf-8")
    return package


def _transcript() -> Transcript:
    return Transcript(
        duration=2.0, segments=[], timing_source="forced_alignment",
        words=[
            TranscriptWord(start=0.10, end=0.30, text="alpha", char_start=0, char_end=5),
            TranscriptWord(start=0.40, end=0.60, text="beta", char_start=6, char_end=10),
            TranscriptWord(start=0.90, end=1.20, text="gamma", char_start=11, char_end=16),
        ],
    )


def test_v12_loader_accepts_semantic_events_global_spans_relation_type_and_compound(tmp_path: Path) -> None:
    model = FinalPackageLoader().load(_write_package(tmp_path), tmp_path / "work")
    scene = model.scenes[0]
    binding = model.semantic_bindings["scenes"][0]

    assert model.manifest["package_version"] == "1.2"
    assert [row["semantic_event_id"] for row in scene.semantic_events] == ["E1", "E2"]
    assert scene.semantic_progression["event_order"] == ["E1", "E2"]
    assert binding["relations"][0]["relation_type"] == "ENABLES"
    compound = next(row for row in binding["assets"] if row["asset_id"] == "c")
    assert compound["compound_visual_classification"] == "COMPOUND_REQUIRED"
    assert compound["internal_progression_unavailable"] is True


def test_v12_spoken_word_to_event_to_icon_to_relation_to_result_chain(tmp_path: Path) -> None:
    package = FinalPackageLoader().load(_write_package(tmp_path), tmp_path / "work")
    scene = package.scenes[0]
    assets = [
        VisualAsset(
            id=asset_id, scene_id=scene.id, role="support",
            image_path=scene.image_path, extraction_method="test",
            source_area_ratio=area,
        )
        for asset_id, area in (("a", 0.50), ("b", 0.30), ("c", 0.20))
    ]
    story = StoryPlanner().plan(package, _transcript(), assets)
    beat = story[0]
    rows = {row.asset_id: row for row in beat.asset_activations}

    assert rows["a"].spoken_start == pytest.approx(0.10)
    assert rows["b"].spoken_start == pytest.approx(0.40)
    assert rows["c"].spoken_start == pytest.approx(0.90)
    assert rows["a"].semantic_event_id == "E1"
    assert {"LEADER", "TEXT_ANCHOR"}.issubset(rows["a"].semantic_event_roles)
    assert rows["c"].semantic_event_id == "E2"
    assert {"LEADER", "RESULT", "TEXT_ANCHOR"}.issubset(rows["c"].semantic_event_roles)
    assert rows["c"].semantic_event_dependency_ids == ["E1"]

    choreography = ChoreographyDirector().plan(package, story, assets)
    directive = choreography.for_beat(beat.id)
    assert directive is not None
    assert directive.pattern == ChoreographyPattern.CAUSE_EFFECT_CHAIN
    assert directive.relationship == "ENABLES"
    assert directive.interaction is not None
    assert directive.interaction.subject_asset_id == "a"
    assert directive.interaction.object_asset_id == "b"
    assert directive.interaction.result_asset_id == "c"
    assert [flow.event_id for flow in directive.event_flows] == ["E1", "E2"]
    assert directive.event_flows[0].leader_asset_ids == ("a",)
    assert directive.event_flows[0].participant_asset_ids == ("b",)
    assert directive.event_flows[0].interactions == (directive.interaction,)
    assert directive.event_flows[1].leader_asset_ids == ("c",)
    assert directive.event_flows[1].result_asset_ids == ("c",)
    assert directive.event_flows[1].dependency_ids == ("E1",)
    assert directive.event_focus_path_asset_ids == ("a", "b", "c")
    assert directive.event_flows[0].handoff_to_event_id == "E2"
    assert directive.event_flows[0].handoff_to_asset_id == "c"
    assert "final_package_event_flow_choreography" in directive.package_evidence
    assert {stage.value for stage in directive.grammar_stages} >= {
        "ADD", "RELATE", "RESULT"
    }

    text = TextPlanner().plan(
        transcript=_transcript(), story=story, package=package, choreography=choreography
    )
    assert [(cue.text, cue.anchor_asset_id) for cue in text.cues] == [("gamma", "c")]
    assert text.cues[0].spoken_start == pytest.approx(0.90)
    assert "final_package_text_anchor" in text.cues[0].package_evidence

    composition = [CompositionBeat(
        beat_id=beat.id,
        items=[
            LayoutItem(asset_id="a", x=0.20, y=0.50, width=0.15, height=0.20),
            LayoutItem(asset_id="b", x=0.50, y=0.50, width=0.15, height=0.20),
            LayoutItem(asset_id="c", x=0.80, y=0.50, width=0.15, height=0.20),
        ],
    )]
    motion = {
        cue.asset_id: cue
        for cue in MotionPlanner().plan(story, composition, choreography, assets=assets)
    }

    assert [motion[row].start for row in ("a", "b", "c")] == pytest.approx([0.10, 0.40, 0.90])
    assert motion["c"].params["semantic_focus"]["role"] == "RESULT"
    assert motion["c"].params["semantic_focus"]["semantic_event_id"] == "E2"
    assert motion["c"].params["motion_order"]["semantic_event_dependency_ids"] == ["E1"]
    subject_frames = motion["a"].params["program"]["keyframes"]
    result_frames = motion["c"].params["program"]["keyframes"]
    assert any(float(frame["dx"]) > 0.0 for frame in subject_frames[1:-1])
    assert max(float(frame["scale"]) for frame in result_frames) > 1.0
    assert result_frames[-1]["dx"] == pytest.approx(0.0)
    assert result_frames[-1]["dy"] == pytest.approx(0.0)
    assert result_frames[-1]["scale"] == pytest.approx(1.0)

    coverage = StorytellingValidator.inspect(
        package=package,
        story=story,
        choreography=choreography,
        composition=composition,
        motion=list(motion.values()),
        text=text,
        text_motion=[],
    )
    assert coverage.explicit_relationships >= 1
    assert coverage.represented_relationships >= coverage.explicit_relationships
    assert coverage.authored_semantic_events == 2
    assert coverage.represented_semantic_events == 2
    assert coverage.missing_semantic_events == ()


def test_v12_compound_required_multi_cutout_unit_never_internal_staggers() -> None:
    activations = [
        AssetActivation(
            asset_id=asset_id, semantic_unit_id="compound", semantic_group_id="g",
            sequence_order=1, source="final_package_semantic_binding", policy="EXPLICIT",
            trigger_char_start=0, trigger_char_end=5, spoken_start=0.1, spoken_end=0.8,
            compound_visual_classification="COMPOUND_REQUIRED",
            internal_progression_unavailable=True,
            evidence=["visual_identity_multi_cutout_member"],
        )
        for asset_id in ("piece-a", "piece-b", "piece-c")
    ]
    beat = StoryBeat(
        id="b", scene_id="s", start=0, end=1, audio_start=0, audio_end=1,
        narration="alpha", support_asset_ids=[row.asset_id for row in activations],
        action="INTRODUCE", asset_activations=activations,
    )
    items = [
        LayoutItem(asset_id="piece-c", x=.7, y=.5, width=.15, height=.15),
        LayoutItem(asset_id="piece-a", x=.3, y=.5, width=.15, height=.15),
        LayoutItem(asset_id="piece-b", x=.5, y=.5, width=.15, height=.15),
    ]

    ordered = MotionOrderResolver().resolve(beat=beat, items=items)
    assert all(slot.internal_count == 1 and slot.internal_index == 0 for slot in ordered)
    cues = MotionPlanner().plan([beat], [CompositionBeat(beat_id="b", items=items)])
    assert len({cue.start for cue in cues}) == 1
    assert all(not cue.params["motion_order"]["stagger_applied"] for cue in cues)


def test_v12_text_anchor_metadata_beats_beat_primary_when_spans_tie() -> None:
    beat = StoryBeat(
        id="b", scene_id="s", start=0, end=1, narration="alpha", action="INTRODUCE",
        primary_asset_ids=["visual-primary"],
        asset_activations=[
            AssetActivation(
                asset_id="visual-primary", trigger_char_start=0, trigger_char_end=5,
                confidence=.99, visual_focus="PRIMARY", semantic_event_roles=["LEADER"],
            ),
            AssetActivation(
                asset_id="text-anchor", trigger_char_start=0, trigger_char_end=5,
                confidence=.95, visual_focus="SUPPORT", semantic_event_roles=["TEXT_ANCHOR"],
            ),
        ],
    )
    candidate = KeywordCandidate(
        display_text="alpha", semantic_type="keyword",
        source_char_start=0, source_char_end=5, score=.9,
    )
    assert TextPlanner._anchor_asset_id(
        beat=beat, candidate=candidate, directive=None
    ) == "text-anchor"


def test_v12_event_leader_wins_same_time_attention_over_context() -> None:
    rows = [
        AssetActivation(
            asset_id="context", semantic_unit_id="ctx", semantic_group_id="g",
            sequence_order=1, source="final_package_semantic_binding", policy="SEMANTIC",
            spoken_start=0.1, spoken_end=0.8, trigger_char_start=0, trigger_char_end=5,
            semantic_event_id="E1", semantic_event_order=1,
            semantic_event_roles=["CONTEXT"], visual_focus="SUPPORT",
        ),
        AssetActivation(
            asset_id="leader", semantic_unit_id="leader", semantic_group_id="g",
            sequence_order=1, source="final_package_semantic_binding", policy="EXPLICIT",
            spoken_start=0.1, spoken_end=0.8, trigger_char_start=0, trigger_char_end=5,
            semantic_event_id="E1", semantic_event_order=1,
            semantic_event_roles=["LEADER", "TEXT_ANCHOR"], visual_focus="PRIMARY",
        ),
    ]
    beat = StoryBeat(
        id="b", scene_id="s", start=0, end=1, audio_start=0, audio_end=1,
        narration="alpha", primary_asset_ids=["context"], support_asset_ids=["leader"],
        action="INTRODUCE",
    )
    beat.asset_activations = schedule_windows(rows, beat, beat.end, set())
    layout = CompositionBeat(
        beat_id="b",
        items=[
            LayoutItem(asset_id="context", x=.25, y=.5, width=.4, height=.5),
            LayoutItem(asset_id="leader", x=.7, y=.5, width=.18, height=.18),
        ],
    )
    cues = {
        cue.asset_id: cue
        for cue in MotionPlanner().plan([beat], [layout], ChoreographyPlan())
    }
    assert cues["leader"].params["semantic_focus"]["cohort_role"] in {"leader", "leader_member"}
    assert cues["leader"].params["semantic_focus"]["cohort_gain"] == pytest.approx(1.0)
    assert cues["context"].params["semantic_focus"]["cohort_role"] == "quiet"


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg required")
def test_v12_semantic_package_reaches_encoded_motion_end_to_end(tmp_path: Path) -> None:
    """Prove the rich V1.2 contract survives through a real encoded MP4.

    This is intentionally broader than the metadata contract test above:
    FinalPackageLoader -> Story -> Choreography -> Motion segments -> FFmpeg ->
    encoded semantic-motion QA.
    """
    package = FinalPackageLoader().load(_write_package(tmp_path), tmp_path / "work-render")
    scene = package.scenes[0]

    cutout_root = tmp_path / "cutouts"
    cutout_root.mkdir()
    specs = (
        ("a", (215, 55, 55, 255), 0.20, 0.50),
        ("b", (45, 115, 220, 255), 0.50, 0.50),
        ("c", (55, 175, 85, 255), 0.80, 0.50),
    )
    assets: list[VisualAsset] = []
    items: list[LayoutItem] = []
    for index, (asset_id, color, x, y) in enumerate(specs):
        path = cutout_root / f"{asset_id}.png"
        Image.new("RGBA", (140, 140), color).save(path)
        assets.append(VisualAsset(
            id=asset_id,
            scene_id=scene.id,
            role="support",
            image_path=path,
            extraction_method="v12-render-contract",
            source_area_ratio=0.30 - index * 0.05,
        ))
        items.append(LayoutItem(
            asset_id=asset_id,
            x=x,
            y=y,
            width=0.18,
            height=0.28,
            z=10 + index,
        ))

    transcript = _transcript()
    story = StoryPlanner().plan(package, transcript, assets)
    choreography = ChoreographyDirector().plan(package, story, assets)
    composition = [CompositionBeat(beat_id=story[0].id, items=items)]
    motion = MotionPlanner().plan(story, composition, choreography, assets=assets)

    interaction = MotionInteractionQA().inspect(story=story, motion=motion)
    assert interaction.ok, interaction.violations
    assert interaction.checked_relations >= 1

    plan = RenderPlan(
        width=640,
        height=360,
        fps=30,
        duration=transcript.duration,
        story=story,
        composition=composition,
        motion=motion,
        assets=assets,
    )
    output = tmp_path / "v12-semantic-motion.mp4"
    FFmpegRenderer("ffmpeg").render(plan, output)

    assert output.is_file() and output.stat().st_size > 0
    encoded = RenderedMotionQA().inspect(video=output, plan=plan)
    assert encoded.ok, encoded.violations
    assert encoded.checked_segments >= 2



def test_v12_relation_without_own_span_inherits_authored_asset_envelope(tmp_path: Path) -> None:
    package_path = _write_package(tmp_path)
    for filename in ("scene_plan.json", "semantic_bindings.json"):
        path = package_path / filename
        payload = json.loads(path.read_text(encoding="utf-8"))
        scenes = payload["scenes"]
        for scene in scenes:
            for relation in scene.get("relations", []):
                relation.pop("script_span", None)
                relation.pop("script_text", None)
        path.write_text(json.dumps(payload), encoding="utf-8")

    package = FinalPackageLoader().load(package_path, tmp_path / "work-spanless-relation")
    scene = package.scenes[0]
    assets = [
        VisualAsset(
            id=asset_id,
            scene_id=scene.id,
            role="support",
            image_path=scene.image_path,
            extraction_method="test",
            source_area_ratio=area,
        )
        for asset_id, area in (("a", 0.50), ("b", 0.30), ("c", 0.20))
    ]
    story = StoryPlanner().plan(package, _transcript(), assets)
    beat = story[0]
    relation = next(
        row
        for row in beat.semantic_context.relations
        if row.authority == "FINAL_PACKAGE_ASSET_RELATION"
    )
    assert relation.trigger_char_start == 0
    assert relation.trigger_char_end == 16
    assert relation.spoken_start == pytest.approx(0.10)
    assert relation.spoken_end == pytest.approx(1.20)

    choreography = ChoreographyDirector().plan(package, story, assets)
    composition = [CompositionBeat(
        beat_id=beat.id,
        items=[
            LayoutItem(asset_id="a", x=0.20, y=0.50, width=0.15, height=0.20),
            LayoutItem(asset_id="b", x=0.50, y=0.50, width=0.15, height=0.20),
            LayoutItem(asset_id="c", x=0.80, y=0.50, width=0.15, height=0.20),
        ],
    )]
    motion = MotionPlanner().plan(story, composition, choreography, assets=assets)
    report = MotionInteractionQA().inspect(
        story=story,
        motion=motion,
        composition=composition,
        choreography=choreography,
    )
    assert report.ok, report.violations
    assert report.checked_relations >= 1

    stripped = [cue.model_copy(update={"segments": []}) for cue in motion]
    missing = MotionInteractionQA().inspect(
        story=story,
        motion=stripped,
        composition=composition,
        choreography=choreography,
    )
    assert not missing.ok
    assert any(row.code == "MISSING_RELATION_TIMELINE" for row in missing.violations)
