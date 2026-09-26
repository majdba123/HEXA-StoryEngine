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
from app.story.activation import SemanticActivationPlanner
from app.story.planner import StoryPlanner
from app.story.windows import StoryAssetActivation, schedule_windows
from app.shared.errors import StageFailedError
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
    # Explicit semantic meaning executes once in its dedicated timeline. ENTRY remains
    # a clean arrival so the viewer does not receive a micro-interaction immediately
    # followed by the real INTERACT/PAYOFF accent.
    assert not str(motion["a"].params["program"]["name"]).startswith("event_chain_")
    assert not str(motion["c"].params["program"]["name"]).startswith("event_chain_")
    subject_interact = next(row for row in motion["a"].segments if row.phase == "INTERACT")
    result_payoff = next(row for row in motion["c"].segments if row.phase == "PAYOFF")
    subject_frames = subject_interact.program["keyframes"]
    result_frames = result_payoff.program["keyframes"]
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



def test_v12_relation_authority_completes_gray_hat_style_motion_contract(tmp_path: Path) -> None:
    """Production regression for diagnostic 10f16ca6 relation-completeness class."""
    package_path = _write_package(tmp_path)
    for filename in ("scene_plan.json", "semantic_bindings.json"):
        path = package_path / filename
        payload = json.loads(path.read_text(encoding="utf-8"))
        scenes = payload["scenes"]
        for scene in scenes:
            relation = scene["relations"][0]
            relation["relation_type"] = "DISCOVERS"
            relation.pop("script_span", None)
            relation.pop("script_text", None)
            for event in scene.get("semantic_events", []):
                if event["semantic_event_id"] == "E2":
                    event["result_asset_ids"] = []
        if filename == "semantic_bindings.json":
            for event in payload.get("semantic_events", []):
                if event["semantic_event_id"] == "E2":
                    event["result_asset_ids"] = []
        path.write_text(json.dumps(payload), encoding="utf-8")

    package = FinalPackageLoader().load(
        package_path,
        tmp_path / "work-gray-relation-contract",
    )
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
    choreography = ChoreographyDirector().plan(package, story, assets)
    beat = story[0]
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
    assert report.checked_relations == 1

    by_id = {cue.asset_id: cue for cue in motion}
    assert any(segment.phase == "INTERACT" for segment in by_id["a"].segments)
    assert not any(segment.phase == "REACT" for segment in by_id["b"].segments)
    assert any(segment.phase == "PAYOFF" for segment in by_id["c"].segments)



@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg required")
def test_v12_gray_hat_relation_contract_reaches_encoded_qa(tmp_path: Path) -> None:
    """Encode the 10f16ca6 failure class; metadata-only success is insufficient."""
    package_path = _write_package(tmp_path)
    for filename in ("scene_plan.json", "semantic_bindings.json"):
        path = package_path / filename
        payload = json.loads(path.read_text(encoding="utf-8"))
        for scene_row in payload["scenes"]:
            relation = scene_row["relations"][0]
            relation["relation_type"] = "DISCOVERS"
            relation.pop("script_span", None)
            relation.pop("script_text", None)
            for event in scene_row.get("semantic_events", []):
                if event["semantic_event_id"] == "E2":
                    event["result_asset_ids"] = []
        if filename == "semantic_bindings.json":
            for event in payload.get("semantic_events", []):
                if event["semantic_event_id"] == "E2":
                    event["result_asset_ids"] = []
        path.write_text(json.dumps(payload), encoding="utf-8")

    package = FinalPackageLoader().load(package_path, tmp_path / "work-gray-encoded")
    scene = package.scenes[0]
    cutout_root = tmp_path / "gray-cutouts"
    cutout_root.mkdir()
    specs = (
        ("a", (215, 55, 55, 255), 0.20),
        ("b", (45, 115, 220, 255), 0.50),
        ("c", (55, 175, 85, 255), 0.80),
    )
    assets: list[VisualAsset] = []
    items: list[LayoutItem] = []
    for index, (asset_id, color, x) in enumerate(specs):
        image_path = cutout_root / f"{asset_id}.png"
        Image.new("RGBA", (140, 140), color).save(image_path)
        assets.append(VisualAsset(
            id=asset_id,
            scene_id=scene.id,
            role="support",
            image_path=image_path,
            extraction_method="gray-relation-render-contract",
            source_area_ratio=0.30 - index * 0.05,
        ))
        items.append(LayoutItem(
            asset_id=asset_id,
            x=x,
            y=0.50,
            width=0.18,
            height=0.28,
            z=10 + index,
        ))

    transcript = _transcript()
    story = StoryPlanner().plan(package, transcript, assets)
    choreography = ChoreographyDirector().plan(package, story, assets)
    composition = [CompositionBeat(beat_id=story[0].id, items=items)]
    motion = MotionPlanner().plan(story, composition, choreography, assets=assets)

    interaction = MotionInteractionQA().inspect(
        story=story,
        motion=motion,
        composition=composition,
        choreography=choreography,
    )
    assert interaction.ok, interaction.violations
    assert interaction.checked_relations == 1

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
    output = tmp_path / "gray-relation-contract.mp4"
    FFmpegRenderer("ffmpeg").render(plan, output)

    assert output.is_file() and output.stat().st_size > 0
    encoded = RenderedMotionQA().inspect(video=output, plan=plan)
    assert encoded.ok, encoded.violations
    assert encoded.checked_segments >= 3



def test_v12_relation_without_explicit_result_does_not_borrow_event_result(tmp_path: Path) -> None:
    """Relation and semantic-event result are independent Final Package authorities."""
    package_path = _write_package(tmp_path)
    for filename in ("scene_plan.json", "semantic_bindings.json"):
        path = package_path / filename
        payload = json.loads(path.read_text(encoding="utf-8"))
        scene = payload["scenes"][0]
        relation = scene["relations"][0]
        relation.pop("result_asset_id", None)
        relation["relation_type"] = "CONTRASTS_WITH"
        path.write_text(json.dumps(payload), encoding="utf-8")

    package = FinalPackageLoader().load(package_path, tmp_path / "work-no-relation-result")
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
    choreography = ChoreographyDirector().plan(package, story, assets)
    directive = choreography.for_beat(story[0].id)
    assert directive is not None and directive.interaction is not None

    # The authored relation has no result. Do not manufacture one from E2's RESULT.
    assert directive.interaction.relationship == "CONTRASTS_WITH"
    assert directive.interaction.result_asset_id is None

    by_event = {flow.event_id: flow for flow in directive.event_flows}
    assert by_event["E2"].result_asset_ids == ("c",)
    payoff = next(
        step for step in by_event["E2"].steps
        if step.stage.value == "PAYOFF" and step.result_asset_id == "c"
    )
    assert payoff.relationship is None

    composition = [CompositionBeat(
        beat_id=story[0].id,
        items=[
            LayoutItem(asset_id="a", x=0.20, y=0.50, width=0.15, height=0.20),
            LayoutItem(asset_id="b", x=0.50, y=0.50, width=0.15, height=0.20),
            LayoutItem(asset_id="c", x=0.80, y=0.50, width=0.15, height=0.20),
        ],
    )]
    motion = MotionPlanner().plan(story, composition, choreography, assets=assets)
    report = MotionInteractionQA().inspect(
        story=story, motion=motion, composition=composition, choreography=choreography,
    )
    assert report.ok, report.violations
    assert any(
        segment.phase == "PAYOFF"
        for cue in motion if cue.asset_id == "c"
        for segment in cue.segments
    )


def test_v12_compound_child_event_reuses_parent_cutout_without_new_asset(tmp_path: Path) -> None:
    """Unextracted authored child events refocus their explicit compound parent."""
    package_path = _write_package(tmp_path)
    for filename in ("scene_plan.json", "semantic_bindings.json"):
        path = package_path / filename
        payload = json.loads(path.read_text(encoding="utf-8"))
        scenes = payload["scenes"]
        for scene in scenes:
            for asset in scene.get("assets", []):
                if asset.get("asset_id") == "b":
                    asset["binding_type"] = "PARENT"
                    asset["children_asset_ids"] = ["c"]
                if asset.get("asset_id") == "c":
                    asset["binding_type"] = "SUPPORT"
                    asset["parent_asset_id"] = "b"
                    asset["visual_locator"] = None
            # Keep E2 fully authored but make c unavailable as an independent cutout.
            scene["relations"] = []
        path.write_text(json.dumps(payload), encoding="utf-8")

    package = FinalPackageLoader().load(package_path, tmp_path / "work-compound-proxy")
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
        for asset_id, area in (("a", 0.50), ("b", 0.30))
    ]
    story = StoryPlanner().plan(package, _transcript(), assets)
    beat = story[0]

    assert {row.asset_id for row in beat.asset_activations} == {"a", "b"}
    assert len(beat.semantic_event_proxies) == 1
    proxy = beat.semantic_event_proxies[0]
    assert proxy.asset_id == "b"
    assert proxy.semantic_unit_id == "c"
    assert proxy.semantic_parent_id == "b"
    assert proxy.semantic_event_id == "E2"
    assert proxy.reveal_start >= proxy.spoken_start

    choreography = ChoreographyDirector().plan(package, story, assets)
    directive = choreography.directives[0]
    assert {flow.event_id for flow in directive.event_flows} == {"E1", "E2"}
    proxy_flow = next(flow for flow in directive.event_flows if flow.event_id == "E2")
    assert proxy_flow.leader_asset_ids == ("b",)
    proxy_steps = [
        step for step in proxy_flow.steps
        if step.authority == "FINAL_PACKAGE_COMPOUND_PROXY"
    ]
    assert len(proxy_steps) == 1
    assert proxy_steps[0].stage.value == "PAYOFF"

    composition = [CompositionBeat(
        beat_id=beat.id,
        items=[
            LayoutItem(asset_id="a", x=0.30, y=0.50, width=0.20, height=0.30),
            LayoutItem(asset_id="b", x=0.70, y=0.50, width=0.20, height=0.30),
        ],
    )]
    motion = MotionPlanner().plan(story, composition, choreography, assets=assets)
    b_cue = next(cue for cue in motion if cue.asset_id == "b")
    proxy_segments = [
        segment for segment in b_cue.segments
        if segment.semantic_event_id == "E2"
    ]
    assert len(proxy_segments) == 1
    assert proxy_segments[0].phase == "PAYOFF"

    from app.story import StorySyncQA

    sync = StorySyncQA().inspect(story=story, motion=motion)
    assert not [
        violation for violation in sync.violations
        if proxy.semantic_event_id in violation and "proxy_" in violation
    ], sync.violations
    assert any(
        entry.activation_policy == "COMPOUND_PROXY"
        and entry.semantic_unit_id == "c"
        for entry in sync.entries
    )

    text = TextPlanner().plan(
        transcript=_transcript(),
        story=story,
        assets=assets,
        package=package,
        choreography=choreography,
    )
    report = StorytellingValidator().inspect(
        package=package,
        story=story,
        choreography=choreography,
        composition=composition,
        motion=motion,
        text=text,
        text_motion=[],
    )
    assert report.missing_semantic_events == ()
    assert report.represented_semantic_events == report.authored_semantic_events


def test_historical_relation_and_handoff_failures_remain_strictly_rejected(
    tmp_path: Path,
) -> None:
    """Lock historical Gray/Black semantic-motion failure classes as regressions."""
    package_path = _write_package(tmp_path)
    for filename in ("scene_plan.json", "semantic_bindings.json"):
        path = package_path / filename
        payload = json.loads(path.read_text(encoding="utf-8"))
        for scene_row in payload["scenes"]:
            relation = scene_row["relations"][0]
            relation["relation_type"] = "DISCOVERS"
            relation.pop("script_span", None)
            relation.pop("script_text", None)
            for event in scene_row.get("semantic_events", []):
                if event["semantic_event_id"] == "E2":
                    event["result_asset_ids"] = []
        if filename == "semantic_bindings.json":
            for event in payload.get("semantic_events", []):
                if event["semantic_event_id"] == "E2":
                    event["result_asset_ids"] = []
        path.write_text(json.dumps(payload), encoding="utf-8")

    package = FinalPackageLoader().load(package_path, tmp_path / "work-historical-failures")
    scene = package.scenes[0]
    assets = [
        VisualAsset(
            id=asset_id,
            scene_id=scene.id,
            role="support",
            image_path=scene.image_path,
            extraction_method="historical-failure-regression",
            source_area_ratio=area,
        )
        for asset_id, area in (("a", 0.50), ("b", 0.30), ("c", 0.20))
    ]
    story = StoryPlanner().plan(package, _transcript(), assets)
    choreography = ChoreographyDirector().plan(package, story, assets)
    beat = story[0]
    composition = [CompositionBeat(
        beat_id=beat.id,
        items=[
            LayoutItem(asset_id="a", x=0.20, y=0.50, width=0.15, height=0.20),
            LayoutItem(asset_id="b", x=0.50, y=0.50, width=0.15, height=0.20),
            LayoutItem(asset_id="c", x=0.80, y=0.50, width=0.15, height=0.20),
        ],
    )]
    motion = MotionPlanner().plan(story, composition, choreography, assets=assets)
    baseline = MotionInteractionQA().inspect(
        story=story,
        motion=motion,
        composition=composition,
        choreography=choreography,
    )
    assert baseline.ok, baseline.violations

    def without_phase(asset_id: str, phase: str):
        rows = []
        for cue in motion:
            if cue.asset_id != asset_id:
                rows.append(cue)
                continue
            rows.append(cue.model_copy(update={
                "segments": [
                    segment for segment in cue.segments
                    if segment.phase != phase
                ],
            }))
        return rows

    reveal_without_duplicate_reaction = MotionInteractionQA().inspect(
        story=story,
        motion=without_phase("b", "REACT"),
        composition=composition,
        choreography=choreography,
    )
    assert not any(
        row.code == "MISSING_TARGET_REACTION"
        for row in reveal_without_duplicate_reaction.violations
    )

    missing_payoff = MotionInteractionQA().inspect(
        story=story,
        motion=without_phase("c", "PAYOFF"),
        composition=composition,
        choreography=choreography,
    )
    assert any(
        row.code == "MISSING_RESULT_PAYOFF"
        for row in missing_payoff.violations
    )
    with pytest.raises(StageFailedError) as payoff_error:
        MotionInteractionQA.require(missing_payoff)
    assert payoff_error.value.effective_code == "MISSING_RESULT_PAYOFF"

    mutated_motion = list(motion)
    source_index = next(
        index for index, cue in enumerate(mutated_motion)
        if cue.segments
    )
    source_cue = mutated_motion[source_index]
    source_segment = source_cue.segments[0]
    bad_segment = source_segment.model_copy(update={
        "handoff_deadline": max(
            source_segment.start,
            source_segment.end - 0.01,
        ),
    })
    mutated_motion[source_index] = source_cue.model_copy(update={
        "segments": [bad_segment, *source_cue.segments[1:]],
    })
    past_handoff = MotionInteractionQA().inspect(
        story=story,
        motion=mutated_motion,
        composition=composition,
        choreography=choreography,
    )
    assert any(
        row.code == "SEGMENT_PAST_HANDOFF"
        for row in past_handoff.violations
    )
    with pytest.raises(StageFailedError) as handoff_error:
        MotionInteractionQA.require(past_handoff)
    assert handoff_error.value.effective_code == "SEGMENT_PAST_HANDOFF"


def test_event_dependency_anchor_prefers_leader_over_late_support() -> None:
    leader = StoryAssetActivation(
        asset_id="leader",
        semantic_unit_id="leader-unit",
        confidence=0.99,
        source="final_package_semantic_binding",
        policy="EXACT",
        semantic_event_id="E1",
        semantic_event_order=1,
        semantic_event_roles=["LEADER", "TEXT_ANCHOR"],
        visual_focus="PRIMARY",
        phrase_start=0.10, phrase_end=0.70, reveal_start=0.10,
        semantic_peak=0.40, settle_at=0.60, activation_policy="OWN_WINDOW",
    )
    support = StoryAssetActivation(
        asset_id="support",
        semantic_unit_id="support-unit",
        confidence=0.95,
        source="final_package_semantic_binding",
        policy="EXACT",
        semantic_event_id="E1",
        semantic_event_order=1,
        semantic_event_roles=["PARTICIPANT"],
        visual_focus="SUPPORT",
        phrase_start=0.80, phrase_end=1.60, reveal_start=0.80,
        semantic_peak=1.40, settle_at=1.55, activation_policy="OWN_WINDOW",
    )

    anchors = SemanticActivationPlanner._canonical_event_anchor_peaks(
        [leader, support], renderable_ids={"leader", "support"}
    )

    assert anchors["E1"] == pytest.approx(0.40)


def test_v12_group_event_proxy_preserves_unresolved_authored_event_without_new_asset(tmp_path: Path) -> None:
    """An unresolved semantic-group member keeps its authored event via one real carrier."""
    package_path = _write_package(tmp_path)
    for filename in ("scene_plan.json", "semantic_bindings.json"):
        path = package_path / filename
        payload = json.loads(path.read_text(encoding="utf-8"))
        scene = payload["scenes"][0]
        # Make c an authored later event in the same semantic group, but remove all
        # direct identity evidence so no independent cutout can be resolved.
        for asset in scene.get("assets", []):
            if asset.get("asset_id") == "c":
                asset["parent_asset_id"] = None
                asset["visual_locator"] = None
                asset["semantic_group_id"] = "G1"
                asset["sequence_order"] = 3
        scene.setdefault("semantic_groups", [{
            "semantic_group_id": "G1",
            "script_text": "alpha beta gamma",
            "animation_policy": "SEQUENTIAL_WITHIN_PHRASE",
            "asset_ids": ["a", "b", "c"],
        }])
        path.write_text(json.dumps(payload), encoding="utf-8")

    package = FinalPackageLoader().load(package_path, tmp_path / "work-group-proxy")    scene = package.scenes[0]
    assets = [
        VisualAsset(
            id=asset_id,
            scene_id=scene.id,
            role="support",
            image_path=scene.image_path,
            extraction_method="test",
            source_area_ratio=area,
        )
        for asset_id, area in (("a", 0.50), ("b", 0.30))
    ]
    story = StoryPlanner().plan(package, _transcript(), assets)
    beat = story[0]

    assert {row.asset_id for row in beat.asset_activations} == {"a", "b"}
    group_proxies = [
        row for row in beat.semantic_event_proxies
        if row.authority == "FINAL_PACKAGE_GROUP_PROXY"
    ]
    assert len(group_proxies) == 1
    proxy = group_proxies[0]
    assert proxy.semantic_unit_id == "c"
    assert proxy.semantic_group_id == "G1"
    assert proxy.semantic_parent_id is None
    assert proxy.semantic_event_id == "E2"
    assert proxy.asset_id in {"a", "b"}

    choreography = ChoreographyDirector().plan(package, story, assets)
    directive = choreography.directives[0]
    assert {flow.event_id for flow in directive.event_flows} == {"E1", "E2"}
    proxy_flow = next(flow for flow in directive.event_flows if flow.event_id == "E2")
    assert proxy.asset_id in proxy_flow.asset_ids
    assert any(
        step.authority == "FINAL_PACKAGE_GROUP_PROXY"
        for step in proxy_flow.steps
    )

    composition = [CompositionBeat(
        beat_id=beat.id,
        items=[
            LayoutItem(asset_id="a", x=0.30, y=0.50, width=0.20, height=0.30),
            LayoutItem(asset_id="b", x=0.70, y=0.50, width=0.20, height=0.30),
        ],
    )]
    motion = MotionPlanner().plan(story, composition, choreography, assets=assets)
    cue = next(row for row in motion if row.asset_id == proxy.asset_id)
    assert any(
        segment.semantic_event_id == "E2"
        for segment in cue.segments
    )

    from app.story import StorySyncQA

    sync = StorySyncQA().inspect(story=story, motion=motion)
    assert not [
        violation for violation in sync.violations
        if proxy.semantic_event_id in violation and "proxy_" in violation
    ], sync.violations