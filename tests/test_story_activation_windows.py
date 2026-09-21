from __future__ import annotations

import json
import math
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.models import (
    AssetActivation, PackageModel, SceneSource, StoryBeat, StoryEntity,
    StorySemanticContext, Transcript, TranscriptWord, VisualAsset,
)
from app.story.activation import SemanticActivationPlanner
from app.story.windows import ScheduledStoryBeat, StoryAssetActivation, schedule_windows


class Scorer:
    def __init__(self, overrides=None):
        self.overrides = overrides or {}
        self.calls = 0

    def score(self, query, candidates):
        self.calls += 1
        name = query.split(" ; ")[0]
        scores = self.overrides.get(name, {name: 0.96})
        return [scores.get(text, 0.1) for text in candidates], True


def scene_case(tmp_path: Path, count=5, duration=12.0):
    labels = [f"concept{i:02}" for i in range(count)]
    words = [TranscriptWord(text=text, start=i * duration / count,
                            end=(i + 0.8) * duration / count)
             for i, text in enumerate(labels)]
    scene = SceneSource(id="s", image_path=tmp_path / "s.png", order=0,
                        units=[{"unit_id": text, "type": "ICON"} for text in labels])
    package = PackageModel(root=tmp_path, package_id="test", scenes=[scene])
    transcript = Transcript(language="en", duration=duration, words=words, segments=[])
    assets = [VisualAsset(id=text, scene_id="s", role="icon",
                          image_path=tmp_path / f"{text}.png", extraction_method="test")
              for text in labels]
    beat = StoryBeat(id="b", scene_id="s", start=0, end=duration,
                     audio_start=0, audio_end=duration, narration=" ".join(labels),
                     action="EXPLAIN", support_asset_ids=labels,
                     semantic_context=StorySemanticContext(entities=[
                         StoryEntity(unit_id=text, semantic_name=text) for text in labels]))
    return package, transcript, assets, beat


@pytest.mark.parametrize("count,duration", [(1, 0.03), (1, 12), (5, 0.1), (5, 12),
                                           (20, 60), (40, 120)])
def test_general_scene_windows_follow_spoken_order(tmp_path, count, duration):
    package, transcript, assets, beat = scene_case(tmp_path, count, duration)
    scorer = Scorer()
    planner = SemanticActivationPlanner(scorer=scorer)
    result = planner.enrich(package, transcript, assets, [beat])[0]
    rows = result.asset_activations
    assert len(rows) == count
    assert scorer.calls == count
    for row, word in zip(rows, transcript.words):
        assert row.trigger_text == word.text
        assert row.activation_policy == "OWN_WINDOW"
        assert all(math.isfinite(t) for t in (row.reveal_start, row.semantic_peak, row.settle_at))
        assert 0 <= row.reveal_start <= row.phrase_start <= row.semantic_peak <= row.settle_at <= duration
        assert row.phrase_start == word.start
        assert row.phrase_end == word.end
    if count > 1:
        assert rows[-1].reveal_start > duration * 0.5
    assert planner.enrich(package, transcript, assets, [beat])[0] == result


def test_joint_assignment_reserves_strong_match_and_uses_confident_alternative(tmp_path):
    package, transcript, assets, beat = scene_case(tmp_path, 2)
    scorer = Scorer({"concept00": {"concept00": 0.92, "concept01": 0.88},
                     "concept01": {"concept00": 0.97}})
    result = SemanticActivationPlanner(scorer=scorer).enrich(package, transcript, assets, [beat])[0]
    rows = {r.asset_id: r for r in result.asset_activations}
    assert rows["concept01"].trigger_text == "concept00"
    assert rows["concept00"].trigger_text == "concept01"


def test_collision_does_not_promote_weak_alternative(tmp_path):
    package, transcript, assets, beat = scene_case(tmp_path, 2)
    scorer = Scorer({"concept00": {"concept00": 0.94},
                     "concept01": {"concept00": 0.93, "concept01": 0.51}})
    result = SemanticActivationPlanner(scorer=scorer).enrich(package, transcript, assets, [beat])[0]
    row = next(r for r in result.asset_activations if r.asset_id == "concept01")
    assert row.activation_policy == "SAFE_ABSTENTION"
    assert row.reveal_start is None and row.spoken_start is None


def test_safe_parent_chain_inherits_exact_window_independent_of_order(tmp_path):
    package, transcript, assets, beat = scene_case(tmp_path, 1)
    child = assets[0].model_copy(update={"id": "child", "parent_asset_id": assets[0].id,
                                         "can_animate_independently": False})
    grandchild = child.model_copy(update={"id": "grandchild", "parent_asset_id": "child"})
    result = SemanticActivationPlanner(scorer=Scorer()).enrich(
        package, transcript, [assets[0], grandchild, child], [beat])[0]
    parent = next(r for r in result.asset_activations if r.asset_id == assets[0].id)
    for row in result.asset_activations:
        assert (row.reveal_start, row.semantic_peak, row.settle_at) == (
            parent.reveal_start, parent.semantic_peak, parent.settle_at)
        if row.asset_id != parent.asset_id:
            assert row.activation_policy == "INHERITED_WINDOW"


def test_unmatched_parent_and_cycle_abstain(tmp_path):
    package, transcript, assets, beat = scene_case(tmp_path, 2)
    assets[0] = assets[0].model_copy(update={"parent_asset_id": assets[1].id,
                                           "can_animate_independently": False})
    assets[1] = assets[1].model_copy(update={"parent_asset_id": assets[0].id,
                                           "can_animate_independently": False})
    result = SemanticActivationPlanner(scorer=Scorer()).enrich(package, transcript, assets, [beat])[0]
    assert all(r.activation_policy == "SAFE_ABSTENTION" and r.reveal_start is None
               for r in result.asset_activations)


def test_early_scene_completion_is_reported_without_fabricated_late_meaning(tmp_path):
    package, transcript, assets, beat = scene_case(tmp_path, 2, 11)
    scorer = Scorer({"concept00": {"concept00": 0.96}, "concept01": {}})
    result = SemanticActivationPlanner(scorer=scorer).enrich(package, transcript, assets, [beat])[0]
    first = result.asset_activations[0]
    assert "EARLY_SCENE_COMPLETION" in first.evidence
    assert "no_confident_unassigned_late_visual_material" in first.evidence
    assert first.settle_at == transcript.words[0].end


def test_late_material_prevents_early_completion(tmp_path):
    package, transcript, assets, beat = scene_case(tmp_path, 5, 11)
    result = SemanticActivationPlanner(scorer=Scorer()).enrich(package, transcript, assets, [beat])[0]
    assert not any("EARLY_SCENE_COMPLETION" in r.evidence for r in result.asset_activations)


def test_window_survives_native_and_base_typed_serialization(tmp_path):
    package, transcript, assets, beat = scene_case(tmp_path, 1)
    result = SemanticActivationPlanner(scorer=Scorer()).enrich(package, transcript, assets, [beat])[0]
    assert ScheduledStoryBeat.model_validate_json(result.model_dump_json()) == result
    legacy = StoryBeat.model_validate(json.loads(result.model_dump_json()))
    restored = StoryAssetActivation.from_legacy(legacy.asset_activations[0])
    assert restored == result.asset_activations[0]
    assert isinstance(restored, AssetActivation)


@pytest.mark.parametrize("start,end", [(float("nan"), 2), (1, float("inf")), (2, 1), (-1, 2), (0, 20)])
def test_invalid_alignment_safely_abstains(tmp_path, start, end):
    *_, beat = scene_case(tmp_path, 1)
    row = AssetActivation.model_construct(asset_id="x", spoken_start=start, spoken_end=end,
                                          policy="SEMANTIC")
    result = schedule_windows([row], beat, 12, set())[0]
    assert result.activation_policy == "SAFE_ABSTENTION"
    assert result.reveal_start is None


def test_contract_rejects_nonmonotonic_window():
    with pytest.raises(ValidationError):
        StoryAssetActivation(asset_id="x", activation_policy="OWN_WINDOW", phrase_start=1,
                             phrase_end=2, reveal_start=1.5, semantic_peak=1.2, settle_at=2)


def test_candidates_include_clauses_and_repeated_occurrences_without_char_offsets(tmp_path):
    _, transcript, _, _ = scene_case(tmp_path, 8)
    words = transcript.words + [TranscriptWord(text="concept00", start=20, end=21)]
    rows = SemanticActivationPlanner()._phrase_candidates(words, None)
    assert any(r.token_count == 8 for r in rows)
    assert len([r for r in rows if r.text == "concept00"]) == 2


def test_metadata_order_does_not_hide_earlier_narration(tmp_path):
    package, transcript, assets, beat = scene_case(tmp_path, 5)
    beat.semantic_targets = [a.id for a in reversed(assets)]
    result = SemanticActivationPlanner(scorer=Scorer()).enrich(package, transcript, assets, [beat])[0]
    assert [r.trigger_text for r in result.asset_activations] == [w.text for w in transcript.words]
