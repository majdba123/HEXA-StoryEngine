from pathlib import Path

from PIL import Image

from app.input.loader import FinalPackageLoader
from app.models import Transcript, TranscriptWord, VisualAsset
from app.story import StoryPlanner


def _package(tmp_path: Path, scene_json: str, script: str = "alpha beta"):
    package = tmp_path / "package"
    (package / "scenes").mkdir(parents=True)
    image = package / "scenes" / "SCENE_001.png"
    Image.new("RGB", (320, 180), "white").save(image)
    (package / "canonical_script.txt").write_text(script, encoding="utf-8")
    (package / "manifest.json").write_text(
        '{"project_id":"generic","scene_plan":"scene_plan.json",'
        '"canonical_script":"canonical_script.txt"}',
        encoding="utf-8",
    )
    (package / "scene_plan.json").write_text(scene_json, encoding="utf-8")
    return FinalPackageLoader().load(package, tmp_path / "work"), image


def _transcript() -> Transcript:
    return Transcript(
        language="en",
        duration=1.2,
        segments=[],
        words=[
            TranscriptWord(start=0.1, end=0.4, text="alpha", char_start=0, char_end=5),
            TranscriptWord(start=0.5, end=0.9, text="beta", char_start=6, char_end=10),
        ],
    )


def test_story_v2_reads_explicit_final_package_relationships(tmp_path: Path) -> None:
    scene_json = '''{
      "project_id":"generic","scenes":[{
        "scene_id":"SCENE_001","order":1,"image":"scenes/SCENE_001.png",
        "script_span":{"global_char_start":0,"global_char_end":9,"text":"alpha beta"},
        "purpose":"Show a reaction to a result.",
        "visual_concept":"An actor reacts to a generic result object.",
        "units":[
          {"unit_id":"RESULT","semantic_name":"operation_result","type":"GROUP","role":"PRIMARY",
           "narrative_function":"SHOW_RESULT","semantic_intent":"EXPLAIN"},
          {"unit_id":"ACTOR","semantic_name":"viewer_actor","type":"SECONDARY_CHARACTER","role":"SUPPORTING",
           "narrative_function":"SHOW_REACTION","semantic_intent":"REACTION",
           "interaction_target":"RESULT","relationship":"REACTS_TO"}
        ],
        "visual_progression":[{"action":"RESULT","targets":["RESULT","ACTOR"],
          "trigger":{"global_char_start":0,"global_char_end":9}}]
      }]}
    '''
    package, image = _package(tmp_path, scene_json)
    assets = [
        VisualAsset(
            id="asset",
            scene_id="SCENE_001",
            role="primary",
            image_path=image,
            extraction_method="test",
        )
    ]

    beat = StoryPlanner().plan(package, _transcript(), assets)[0]
    context = beat.semantic_context

    assert context is not None
    assert {entity.unit_id for entity in context.entities} == {"RESULT", "ACTOR"}
    explicit = [relation for relation in context.relations if relation.authority == "FINAL_PACKAGE_INTERACTION_TARGET"]
    assert len(explicit) == 1
    assert explicit[0].source_unit_id == "ACTOR"
    assert explicit[0].target_unit_id == "RESULT"
    assert explicit[0].kind == "REACTS_TO"
    assert explicit[0].causal is True
    assert context.subject_unit_ids == ["ACTOR"]
    assert context.object_unit_ids == ["RESULT"]
    assert context.confidence >= 0.90


def test_story_v2_preserves_sparse_package_compatibility(tmp_path: Path) -> None:
    scene_json = '''{
      "project_id":"generic","scenes":[{
        "scene_id":"SCENE_001","order":1,"image":"scenes/SCENE_001.png",
        "script_span":{"global_char_start":0,"global_char_end":9,"text":"alpha beta"},
        "visual_progression":[{"action":"EXPLAIN","targets":[],
          "trigger":{"global_char_start":0,"global_char_end":9}}]
      }]}
    '''
    package, image = _package(tmp_path, scene_json)
    assets = [
        VisualAsset(
            id="asset",
            scene_id="SCENE_001",
            role="primary",
            image_path=image,
            extraction_method="test",
        )
    ]

    beat = StoryPlanner().plan(package, _transcript(), assets)[0]

    assert beat.action == "INTRODUCE"
    assert beat.audio_start == 0.1
    assert beat.audio_end == 0.9
    assert beat.semantic_context is not None
    assert beat.semantic_context.entities == []
    assert beat.semantic_context.relations == []
    assert beat.semantic_context.story_role == "SETUP"


def test_story_v2_role_classifier_is_topic_independent(tmp_path: Path) -> None:
    scene_json = '''{
      "project_id":"generic","scenes":[{
        "scene_id":"SCENE_001","order":1,"image":"scenes/SCENE_001.png",
        "script_span":{"global_char_start":0,"global_char_end":9,"text":"alpha beta"},
        "units":[
          {"unit_id":"A","semantic_name":"generic_failure_result","type":"GROUP","role":"PRIMARY",
           "narrative_function":"SHOW_FAILED_RESULT","semantic_intent":"REACTION"}
        ],
        "visual_progression":[{"action":"RESULT","targets":["A"],
          "trigger":{"global_char_start":0,"global_char_end":9}}]
      }]}
    '''
    package, image = _package(tmp_path, scene_json)
    assets = [
        VisualAsset(
            id="asset",
            scene_id="SCENE_001",
            role="primary",
            image_path=image,
            extraction_method="test",
        )
    ]

    beat = StoryPlanner().plan(package, _transcript(), assets)[0]

    # First beat is deliberately SETUP regardless of topic vocabulary; later authoring
    # layers may escalate it using its preserved semantic evidence.
    assert beat.semantic_context is not None
    assert beat.semantic_context.story_role == "SETUP"
    assert beat.semantic_context.result_unit_ids == ["A"]
    assert "SHOW_FAILED_RESULT" in beat.semantic_context.narrative_functions


def test_story_v2_graph_preserves_package_continuity_without_inventing_causality(tmp_path: Path) -> None:
    package = tmp_path / "package-two"
    (package / "scenes").mkdir(parents=True)
    for name in ("SCENE_001.png", "SCENE_002.png"):
        Image.new("RGB", (320, 180), "white").save(package / "scenes" / name)
    script = "alpha beta gamma delta"
    (package / "canonical_script.txt").write_text(script, encoding="utf-8")
    (package / "manifest.json").write_text(
        '{"project_id":"generic","scene_plan":"scene_plan.json",'
        '"canonical_script":"canonical_script.txt"}',
        encoding="utf-8",
    )
    (package / "scene_plan.json").write_text(
        '''{"project_id":"generic","scenes":[
          {"scene_id":"SCENE_001","order":1,"image":"scenes/SCENE_001.png",
           "script_span":{"global_char_start":0,"global_char_end":9,"text":"alpha beta"},
           "units":[{"unit_id":"A","semantic_name":"shared_actor","type":"GROUP","role":"PRIMARY"}],
           "visual_progression":[{"action":"EXPLAIN","targets":["A"],
             "trigger":{"global_char_start":0,"global_char_end":9}}]},
          {"scene_id":"SCENE_002","order":2,"image":"scenes/SCENE_002.png",
           "relation_to_previous":"CONTINUES_EXPLANATION",
           "script_span":{"global_char_start":11,"global_char_end":21,"text":"gamma delta"},
           "units":[{"unit_id":"B","semantic_name":"shared_actor","type":"GROUP","role":"PRIMARY"}],
           "visual_progression":[{"action":"EXPLAIN","targets":["B"],
             "trigger":{"global_char_start":11,"global_char_end":21}}]}
        ]}''',
        encoding="utf-8",
    )
    model = FinalPackageLoader().load(package, tmp_path / "work-two")
    transcript = Transcript(
        language="en",
        duration=2.5,
        segments=[],
        words=[
            TranscriptWord(start=0.2, end=0.5, text="alpha", char_start=0, char_end=5),
            TranscriptWord(start=0.6, end=0.9, text="beta", char_start=6, char_end=10),
            TranscriptWord(start=1.5, end=1.8, text="gamma", char_start=11, char_end=16),
            TranscriptWord(start=1.9, end=2.2, text="delta", char_start=17, char_end=22),
        ],
    )
    assets = [
        VisualAsset(
            id=f"asset-{index}",
            scene_id=scene.id,
            role="primary",
            image_path=scene.image_path,
            extraction_method="test",
        )
        for index, scene in enumerate(model.scenes, start=1)
    ]
    planner = StoryPlanner()
    beats = planner.plan(model, transcript, assets)
    graph = planner.build_graph(beats)

    assert len(graph.nodes) == 2
    continuity = [edge for edge in graph.edges if edge.kind == "CONTINUES_EXPLANATION"]
    assert len(continuity) == 1
    assert continuity[0].authority == "FINAL_PACKAGE_SCENE_RELATION"
    assert continuity[0].causal is False
    identity = [edge for edge in graph.edges if edge.kind == "SHARED_SEMANTIC_IDENTITY"]
    assert len(identity) == 1
    assert identity[0].shared_semantic_names == ["shared_actor"]
    assert identity[0].causal is False
