import pytest

from app.config import Settings
from app.models import PackageModel
from app.pipeline import StoryEnginePipeline
from app.shared.errors import DependencyUnavailableError
from app.story.activation import HybridSemanticTextScorer, SemanticActivationPlanner
from app.models import Transcript


def test_production_settings_reach_story_e5(monkeypatch, tmp_path):
    monkeypatch.delenv("HEXA_SEMANTIC_TEXT_MODEL", raising=False)
    monkeypatch.delenv("HEXA_REQUIRE_SEMANTIC_MODEL", raising=False)
    monkeypatch.setenv("HEXA_WORK_ROOT", str(tmp_path / "work"))
    monkeypatch.setenv("HEXA_OUTPUT_ROOT", str(tmp_path / "out"))
    pipeline = StoryEnginePipeline(Settings.from_env())
    scorer = pipeline.story.activation.scorer
    assert scorer.model_name == "intfloat/multilingual-e5-small"
    assert scorer.required


def test_required_runtime_is_checked_even_without_candidates(monkeypatch, tmp_path):
    scorer = HybridSemanticTextScorer("missing-model", required=True)
    def fail():
        raise RuntimeError("weights missing")
    monkeypatch.setattr(scorer, "_load", fail)
    planner = SemanticActivationPlanner(scorer=scorer)
    with pytest.raises(DependencyUnavailableError) as error:
        planner.enrich(PackageModel(root=tmp_path, package_id="p", scenes=[]),
                       Transcript(language="ar", duration=1, segments=[]), [], [])
    assert error.value.details["code"] == "SEMANTIC_RUNTIME_UNAVAILABLE"
    assert planner.diagnostics["semantic_runtime_available"] is False
    assert planner.diagnostics["runtime_failure_count"] == 1
    assert planner.diagnostics["abstained_count"] == 0


def test_optional_runtime_failure_is_not_silent(monkeypatch, caplog):
    scorer = HybridSemanticTextScorer("missing-model")
    def fail():
        raise RuntimeError("weights missing")
    monkeypatch.setattr(scorer, "_load", fail)
    _, semantic_used = scorer.score("meaning", ["phrase"])
    assert not semantic_used
    assert scorer.runtime_available is False
    assert scorer.runtime_error == "weights missing"
    assert "SEMANTIC_RUNTIME_UNAVAILABLE" in caplog.text


def test_runtime_loads_once(monkeypatch):
    scorer = HybridSemanticTextScorer("model", required=True)
    calls = []
    monkeypatch.setattr(scorer, "_load", lambda: calls.append(True))
    assert scorer.ensure_available() and scorer.ensure_available()
    assert calls == [True]


def test_optional_missing_model_failure_is_reported_once(caplog):
    scorer = HybridSemanticTextScorer(None, required=False)
    assert scorer.ensure_available() is False
    assert scorer.ensure_available() is False
    assert scorer.ensure_available() is False
    assert scorer.runtime_available is False
    messages = [record.message for record in caplog.records
                if "SEMANTIC_RUNTIME_UNAVAILABLE" in record.message]
    assert len(messages) == 1
