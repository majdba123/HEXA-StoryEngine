import json
import sys
from contextlib import nullcontext
from types import SimpleNamespace

import pytest
from PIL import Image

from app.config import Settings
from app.pipeline import StoryEnginePipeline
from app.story.smolvlm import SmolVLMBackend
from app.story.visual_semantic import VisualSemanticResolver
from test_story_visual_semantic import Backend, _case


def fake_runtime(monkeypatch, response, *, fail=False):
    calls = []
    class Tokens:
        shape = (1, 10)
        def __getitem__(self, key):
            return self
    class Processor:
        @classmethod
        def from_pretrained(cls, path, **kwargs):
            calls.append(("processor", path, kwargs))
            return cls()
        def apply_chat_template(self, messages, **kwargs):
            return messages[0]["content"][1]["text"]
        def __call__(self, **kwargs):
            assert kwargs["do_image_splitting"] is False
            return {"input_ids": Tokens()}
        def batch_decode(self, *args, **kwargs):
            return [response]
    class Model:
        @classmethod
        def from_pretrained(cls, path, **kwargs):
            calls.append(("model", path, kwargs))
            return cls()
        def to(self, device):
            assert device == "cpu"
        def eval(self):
            calls.append(("eval",))
        def generate(self, **kwargs):
            calls.append(("generate", kwargs))
            assert kwargs["do_sample"] is False and kwargs["num_beams"] == 1
            assert kwargs["max_new_tokens"] <= 2048
            if fail:
                raise RuntimeError("inference failed")
            return Tokens()
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(
        float32="float32", inference_mode=nullcontext,
    ))
    monkeypatch.setitem(sys.modules, "transformers", SimpleNamespace(
        AutoProcessor=Processor, AutoModelForVision2Seq=Model,
    ))
    return calls


def test_smolvlm_disabled_and_missing_path(tmp_path):
    assert SmolVLMBackend().decide(tmp_path / "absent.png", "inventory") is None
    backend = SmolVLMBackend(str(tmp_path / "missing-model"))
    assert backend.decide(tmp_path / "absent.png", "inventory") is None
    assert backend.runtime_available is False
    assert "directory not found" in backend.runtime_error


@pytest.mark.parametrize("response,accepted", [
    ('{"assets": []}', True), ('explanation {"assets": []}', False),
    ('{"assets":', False), ('[]', False),
])
def test_local_lazy_json_backend(monkeypatch, tmp_path, response, accepted):
    calls = fake_runtime(monkeypatch, response)
    image = tmp_path / "sheet.png"
    Image.new("RGB", (100, 100)).save(image)
    backend = SmolVLMBackend(str(tmp_path))
    assert calls == []
    for _ in range(2):
        result = backend.decide(image, "inventory only")
        assert (result is not None) == accepted
    assert backend.runtime_available is True
    assert backend.inference_seconds is not None
    loads = [row for row in calls if row[0] in {"model", "processor"}]
    assert len(loads) == 2
    assert all(row[2]["local_files_only"] is True for row in loads)


def test_runtime_exception_fails_closed_without_reloading(monkeypatch, tmp_path):
    calls = fake_runtime(monkeypatch, '{}', fail=True)
    image = tmp_path / "sheet.png"
    Image.new("RGB", (100, 100)).save(image)
    backend = SmolVLMBackend(str(tmp_path))
    assert backend.decide(image, "inventory") is None
    assert backend.decide(image, "inventory") is None
    assert backend.runtime_available is False and "inference failed" in backend.runtime_error
    assert sum(row[0] == "model" for row in calls) == 1


@pytest.mark.parametrize("selection", ["none", "smolvlm", "qwen"])
def test_story_backend_selection_does_not_change_director(monkeypatch, tmp_path, selection):
    monkeypatch.setenv("HEXA_VISUAL_SEMANTIC_BACKEND", selection)
    monkeypatch.setenv("HEXA_SMOLVLM_MODEL", str(tmp_path / "smol"))
    monkeypatch.setenv("HEXA_QWEN3_VL_MODEL", str(tmp_path / "qwen"))
    monkeypatch.setenv("HEXA_WORK_ROOT", str(tmp_path / "work"))
    monkeypatch.setenv("HEXA_OUTPUT_ROOT", str(tmp_path / "output"))
    engine = StoryEnginePipeline(Settings.from_env())
    planner = engine.story.activation
    assert engine.director.backend.model_path == str(tmp_path / "qwen")
    if selection == "smolvlm":
        assert isinstance(planner.visual_resolver.backend, SmolVLMBackend)
        assert planner.visual_backend is None
    elif selection == "none":
        assert planner.visual_resolver.backend is None and planner.visual_backend is None
    else:
        assert planner.visual_resolver.backend is planner.visual_backend is engine.director.backend


def test_cache_isolates_backend_model_and_schema(tmp_path):
    scene, assets, beat = _case(tmp_path)
    payload = {"assets": [{"asset_id": "asset-a", "description": "a lock", "category": "object",
                           "semantic": True, "confidence": 0.95}]}
    keys = []
    for name, model in [("qwen", "model-a"), ("smolvlm", "model-a"), ("smolvlm", "model-b")]:
        backend = Backend(payload)
        backend.backend_name, backend.model_path = name, model
        resolver = VisualSemanticResolver(backend, cache_root=tmp_path / "cache")
        keys.append(resolver._inventory_key(scene, assets))
        resolver.resolve(scene=scene, assets=assets, beat=beat)
        assert len(backend.calls) == 1
    assert len(set(keys)) == 3
    resolver._CACHE_VERSION += 1
    assert resolver._inventory_key(scene, assets) not in keys


def test_local_model_fingerprint_invalidates_same_path_cache(tmp_path):
    scene, assets, _ = _case(tmp_path)
    model = tmp_path / "model"
    model.mkdir()
    config = model / "config.json"
    config.write_text('{"version":1}')
    backend = Backend({})
    backend.model_path = str(model)
    resolver = VisualSemanticResolver(backend, cache_root=tmp_path / "cache")
    before = resolver._inventory_key(scene, assets)
    config.write_text('{"version":123}')
    assert resolver._inventory_key(scene, assets) != before


def test_inventory_pages_every_asset_once_without_narration(tmp_path):
    scene, originals, beat = _case(tmp_path)
    assets = [originals[0].model_copy(update={"id": f"a-{i:03}"}) for i in range(55)]
    class InventoryBackend:
        enabled = True
        def __init__(self):
            self.seen = []
        def decide(self, path, prompt):
            assert beat.narration not in prompt
            assert "spoken_start" not in prompt and "phrase candidates" not in prompt
            rows = json.loads(prompt.split("Allowed assets: ", 1)[1])
            assert len(rows) <= 24
            self.seen.extend(row["asset_id"] for row in rows)
            return {"assets": [dict(row, description="a lock", category="object", semantic=True,
                                     confidence=0.95) for row in rows]}
    backend = InventoryBackend()
    resolver = VisualSemanticResolver(backend, cache_root=tmp_path / "cache")
    result = resolver.resolve(scene=scene, assets=assets, beat=beat)
    assert len(result.assets) == 55
    assert backend.seen == [a.id for a in assets]
    assert len(set(backend.seen)) == 55
    resolver.resolve(scene=scene, assets=assets, beat=beat)
    assert len(backend.seen) == 55


def test_inventory_rejects_artifact_even_with_semantic_true(tmp_path):
    scene, assets, beat = _case(tmp_path)
    backend = Backend({"assets": [{"asset_id": assets[0].id, "description": "a shadow",
                                  "category": "shadow", "semantic": True, "confidence": 0.99}]})
    resolver = VisualSemanticResolver(backend, cache_root=tmp_path / "cache")
    assert not resolver.resolve(scene=scene, assets=assets, beat=beat).assets


def test_failed_inventory_does_not_poison_cache(tmp_path):
    scene, assets, beat = _case(tmp_path)
    backend = Backend(None)
    resolver = VisualSemanticResolver(backend, cache_root=tmp_path / "cache")
    resolver.resolve(scene=scene, assets=assets, beat=beat)
    resolver.resolve(scene=scene, assets=assets, beat=beat)
    assert len(backend.calls) == 2
