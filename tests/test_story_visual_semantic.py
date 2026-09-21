from pathlib import Path

from PIL import Image

from app.models import SceneSource, StoryBeat, VisualAsset
from app.story.visual_semantic import VisualSemanticResolver


class Backend:
    enabled = True

    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def decide(self, image_path, prompt):
        self.calls.append((Path(image_path), prompt))
        return self.payload


def _case(tmp_path: Path):
    scene_image = tmp_path / "scene.png"
    a1 = tmp_path / "a1.png"
    a2 = tmp_path / "a2.png"
    Image.new("RGB", (640, 360), "white").save(scene_image)
    Image.new("RGBA", (160, 120), (255, 255, 255, 0)).save(a1)
    Image.new("RGBA", (120, 120), (255, 255, 255, 0)).save(a2)
    scene = SceneSource(id="SCENE_001", image_path=scene_image, order=1)
    assets = [
        VisualAsset(id="asset-a", scene_id=scene.id, role="primary", image_path=a1,
                    extraction_method="test", source_bbox=(10, 10, 100, 100)),
        VisualAsset(id="asset-b", scene_id=scene.id, role="support", image_path=a2,
                    extraction_method="test", source_bbox=(150, 20, 100, 100)),
    ]
    beat = StoryBeat(id="b", scene_id=scene.id, start=0, end=2, audio_start=0,
                     audio_end=2, narration="THIS MUST NOT ENTER INVENTORY PROMPT", action="EXPLAIN")
    return scene, assets, beat


def test_inventory_is_visual_only_and_validates_ids(tmp_path: Path):
    scene, assets, beat = _case(tmp_path)
    backend = Backend({"assets": [
        {"asset_id": "asset-a", "description": "a security shield icon",
         "category": "security", "semantic": True, "confidence": 0.94},
        {"asset_id": "invented", "description": "fake",
         "category": "fake", "semantic": True, "confidence": 0.99},
    ]})
    resolver = VisualSemanticResolver(backend, cache_root=tmp_path / "cache")
    inventory = resolver.resolve(scene=scene, assets=assets, beat=beat)

    assert set(inventory.assets) == {"asset-a"}
    assert inventory.assets["asset-a"].semantic
    assert inventory.contact_sheet_path is not None and inventory.contact_sheet_path.is_file()
    assert len(backend.calls) == 1
    prompt = backend.calls[0][1]
    assert "THIS MUST NOT ENTER INVENTORY PROMPT" not in prompt
    assert "asset-a" in prompt and "asset-b" in prompt


def test_inventory_cache_avoids_repeated_vlm_calls(tmp_path: Path):
    scene, assets, beat = _case(tmp_path)
    payload = {"assets": [{
        "asset_id": "asset-a", "description": "a lock",
        "category": "security", "semantic": True, "confidence": 0.91,
    }]}
    first_backend = Backend(payload)
    first = VisualSemanticResolver(first_backend, cache_root=tmp_path / "cache")
    one = first.resolve(scene=scene, assets=assets, beat=beat)
    assert one.assets["asset-a"].description == "a lock"
    assert len(first_backend.calls) == 1

    second_backend = Backend({"assets": []})
    second = VisualSemanticResolver(second_backend, cache_root=tmp_path / "cache")
    two = second.resolve(scene=scene, assets=assets, beat=beat)
    assert two.assets["asset-a"].description == "a lock"
    assert len(second_backend.calls) == 0


def test_inventory_rejects_low_confidence_or_ambiguous_rows(tmp_path: Path):
    scene, assets, beat = _case(tmp_path)
    backend = Backend({"assets": [
        {"asset_id": "asset-a", "description": "maybe something",
         "category": "unknown", "semantic": False, "confidence": 0.40},
        {"asset_id": "asset-b", "description": "",
         "category": "unknown", "semantic": True, "confidence": 0.99},
    ]})
    resolver = VisualSemanticResolver(backend, cache_root=tmp_path / "cache")
    inventory = resolver.resolve(scene=scene, assets=assets, beat=beat)
    assert inventory.assets == {}



def test_inventory_semantics_can_retrieve_long_phrase_candidates(tmp_path: Path):
    from app.models import TranscriptWord
    from app.story.activation import SemanticActivationPlanner
    from app.story.visual_semantic import VisualSemanticAsset, VisualSemanticInventory
    from test_story_activation_windows import Scorer

    scene, assets, beat = _case(tmp_path)
    words = [
        TranscriptWord(text=text, start=i * 0.3, end=i * 0.3 + 0.25)
        for i, text in enumerate(["one", "two", "three", "four", "five"])
    ]
    scorer = Scorer({"security sequence": {"one two three four": 0.91, "five": 0.72}})
    planner = SemanticActivationPlanner(scorer=scorer)
    candidates = planner._phrase_candidates(words, None)
    inventory = VisualSemanticInventory(scene_id=scene.id, assets={
        assets[0].id: VisualSemanticAsset(
            asset_id=assets[0].id, description="security sequence",
            category="security", confidence=0.95, semantic=True,
        )
    })

    choices = planner._visual_phrase_shortlists(
        inventory=inventory, candidates=candidates, beat=beat,
    )[assets[0].id]

    assert any(row["text"] == "one two three four" for row in choices)


def test_visual_verifier_rejects_phrase_outside_asset_topk(tmp_path: Path, monkeypatch):
    from app.models import StoryEntity
    from app.story.activation import SemanticActivationPlanner, _PhraseCandidate
    from app.story.visual_semantic import VisualSemanticAsset, VisualSemanticInventory
    from test_story_activation_windows import Scorer

    scene, assets, beat = _case(tmp_path)
    beat.semantic_context = None
    backend = Backend({"matches": [{
        "asset_id": assets[0].id, "phrase_index": 1, "confidence": 0.99,
    }]})
    planner = SemanticActivationPlanner(scorer=Scorer(), visual_backend=backend)
    candidates = [
        _PhraseCandidate("allowed", None, None, 0.1, 0.4, 1),
        _PhraseCandidate("not allowed", None, None, 0.5, 0.8, 2),
    ]
    inventory = VisualSemanticInventory(
        scene_id=scene.id,
        assets={assets[0].id: VisualSemanticAsset(
            asset_id=assets[0].id, description="icon", category="icon",
            confidence=0.95, semantic=True,
        )},
        contact_sheet_path=scene.image_path,
        source="test",
    )
    monkeypatch.setattr(
        planner,
        "_visual_phrase_shortlists",
        lambda **kwargs: {assets[0].id: [{
            "index": 0, "text": "allowed", "score": 0.8, "spoken_start": 0.1,
        }]},
    )

    matches = planner._visual_matches(
        scene=scene, assets=assets, entities=[StoryEntity(unit_id="u")],
        candidates=candidates, beat=beat, inventory=inventory,
    )

    assert assets[0].id not in matches.by_asset
