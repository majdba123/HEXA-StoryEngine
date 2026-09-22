import sys
from contextlib import nullcontext
from types import SimpleNamespace

from PIL import Image

from app.config import Settings
from app.pipeline import StoryEnginePipeline
from app.story.florence import FlorenceVisualSemanticBackend
from app.story.visual_semantic import VisualSemanticResolver
from test_story_visual_semantic import _case


def fake_florence_runtime(monkeypatch, caption="a black shield with a padlock"):
    calls = []

    class Token:
        def to(self, device):
            assert device == "cpu"
            return self

    class Inputs(dict):
        def to(self, device):
            assert device == "cpu"
            return self

    class Processor:
        @classmethod
        def from_pretrained(cls, path, **kwargs):
            calls.append(("processor", path, kwargs))
            return cls()

        def __call__(self, **kwargs):
            assert kwargs["text"] == "<MORE_DETAILED_CAPTION>"
            return Inputs(input_ids=Token(), pixel_values=Token())

        def batch_decode(self, *args, **kwargs):
            return ["generated"]

        def post_process_generation(self, raw, *, task, image_size):
            assert task == "<MORE_DETAILED_CAPTION>"
            return {task: caption}

    class Model:
        @classmethod
        def from_pretrained(cls, path, **kwargs):
            calls.append(("model", path, kwargs))
            return cls()

        def to(self, device):
            assert device == "cpu"
            calls.append(("to", device))
            return self

        def eval(self):
            calls.append(("eval",))
            return self

        def generate(self, **kwargs):
            assert kwargs["do_sample"] is False
            assert kwargs["num_beams"] == 1
            assert kwargs["max_new_tokens"] <= 128
            calls.append(("generate",))
            return Token()

    monkeypatch.setitem(
        sys.modules,
        "torch",
        SimpleNamespace(float32="float32", inference_mode=nullcontext),
    )
    monkeypatch.setitem(
        sys.modules,
        "transformers",
        SimpleNamespace(AutoProcessor=Processor, AutoModelForCausalLM=Model),
    )
    return calls


def test_florence_backend_is_lazy_local_and_caption_only(monkeypatch, tmp_path):
    calls = fake_florence_runtime(monkeypatch)
    image = tmp_path / "asset.png"
    Image.new("RGB", (80, 80), "white").save(image)
    backend = FlorenceVisualSemanticBackend(str(tmp_path))
    assert calls == []

    payload = backend.describe_asset(image)

    assert payload["description"] == "a black shield with a padlock"
    assert payload["semantic"] is True
    assert payload["confidence"] == 0.72
    assert backend.runtime_available is True
    loads = [row for row in calls if row[0] in {"processor", "model"}]
    assert len(loads) == 2
    assert all(row[2]["local_files_only"] is True for row in loads)
    assert all(row[2]["trust_remote_code"] is True for row in loads)


def test_florence_rejects_generic_caption(monkeypatch, tmp_path):
    fake_florence_runtime(monkeypatch, caption="object")
    image = tmp_path / "asset.png"
    Image.new("RGB", (80, 80), "white").save(image)
    backend = FlorenceVisualSemanticBackend(str(tmp_path))
    assert backend.describe_asset(image) is None
    assert backend.runtime_available is True


def test_per_asset_inventory_never_receives_narration(tmp_path):
    scene, assets, beat = _case(tmp_path)

    class PerAssetBackend:
        enabled = True
        backend_name = "florence-test"
        inventory_mode = "per_asset"
        inventory_contract_version = 1

        def __init__(self):
            self.calls = []
            self.runtime_available = True
            self.runtime_error = None

        def describe_asset(self, image_path):
            self.calls.append(image_path)
            return {
                "description": "a security shield icon",
                "category": "visual_caption",
                "semantic": True,
                "confidence": 0.72,
            }

    backend = PerAssetBackend()
    resolver = VisualSemanticResolver(backend, cache_root=tmp_path / "cache")
    inventory = resolver.resolve(scene=scene, assets=assets, beat=beat)

    assert set(inventory.assets) == {asset.id for asset in assets}
    assert backend.calls == [asset.image_path for asset in assets]
    assert inventory.contact_sheet_path is None
    assert all(
        "vlm_asset_caption_inventory" in row.evidence
        for row in inventory.assets.values()
    )

    # The second run must be entirely cache-backed.
    resolver = VisualSemanticResolver(backend, cache_root=tmp_path / "cache")
    resolver.resolve(scene=scene, assets=assets, beat=beat)
    assert backend.calls == [asset.image_path for asset in assets]


def test_story_florence_selection_is_separate_from_pass2_and_director(monkeypatch, tmp_path):
    monkeypatch.setenv("HEXA_VISUAL_SEMANTIC_BACKEND", "florence")
    monkeypatch.setenv("HEXA_STORY_FLORENCE_MODEL", str(tmp_path / "story-florence"))
    monkeypatch.setenv("HEXA_QWEN3_VL_MODEL", str(tmp_path / "qwen"))
    monkeypatch.delenv("HEXA_FLORENCE_MODEL", raising=False)
    monkeypatch.setenv("HEXA_WORK_ROOT", str(tmp_path / "work"))
    monkeypatch.setenv("HEXA_OUTPUT_ROOT", str(tmp_path / "output"))

    settings = Settings.from_env()
    engine = StoryEnginePipeline(settings)
    backend = engine.story.activation.visual_resolver.backend

    assert isinstance(backend, FlorenceVisualSemanticBackend)
    assert backend.model_path == str(tmp_path / "story-florence")
    assert engine.story.activation.visual_backend is None
    assert engine.director.backend.model_path == str(tmp_path / "qwen")
    assert engine.cutout_pass2.semantic_backend is None
