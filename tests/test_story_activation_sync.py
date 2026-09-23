from __future__ import annotations

from pathlib import Path

import re

import pytest

from app.models import (
    AssetActivation,
    CompositionBeat,
    LayoutItem,
    PackageModel,
    SceneSource,
    StoryBeat,
    StoryEntity,
    StorySemanticContext,
    Transcript,
    TranscriptWord,
    VisualAsset,
)
from app.motion import MotionPlanner
from app.story.activation import HybridSemanticTextScorer, SemanticActivationPlanner
from app.shared.errors import DependencyUnavailableError


class _FakeSemanticScorer:
    def __init__(self, scores: dict[str, float]) -> None:
        self.scores = scores

    def score(self, query: str, candidates: list[str]) -> tuple[list[float], bool]:
        del query
        return [self.scores.get(candidate, 0.1) for candidate in candidates], True


def _asset(tmp_path: Path, asset_id: str, role: str) -> VisualAsset:
    image = tmp_path / f"{asset_id}.png"
    image.write_bytes(b"x")
    return VisualAsset(
        id=asset_id,
        scene_id="scene-1",
        role=role,
        image_path=image,
        extraction_method="test",
        source_bbox=(10, 10, 100, 100),
        source_canvas_width=400,
        source_canvas_height=300,
        source_area_ratio=0.08,
    )


def _transcript() -> Transcript:
    words = [
        TranscriptWord(start=1.00, end=1.22, text="الهاكر", char_start=0, char_end=6),
        TranscriptWord(start=1.24, end=1.46, text="الأبيض", char_start=7, char_end=13),
        TranscriptWord(start=1.48, end=1.68, text="يحاول", char_start=14, char_end=19),
        TranscriptWord(start=1.70, end=1.92, text="يفكر", char_start=20, char_end=24),
        TranscriptWord(start=1.94, end=2.20, text="بطريقة", char_start=25, char_end=31),
        TranscriptWord(start=2.22, end=2.52, text="مختلفة", char_start=32, char_end=38),
    ]
    return Transcript(
        language="ar",
        duration=3.0,
        segments=[],
        words=words,
        timing_source="forced_alignment",
    )


def _beat() -> StoryBeat:
    return StoryBeat(
        id="beat-001",
        scene_id="scene-1",
        start=0.76,
        end=2.70,
        audio_start=1.0,
        audio_end=2.52,
        narration="الهاكر الأبيض يحاول يفكر بطريقة مختلفة",
        primary_asset_ids=["character"],
        support_asset_ids=["bulb"],
        action="INTRODUCE",
        semantic_targets=["HACKER", "IDEA"],
        semantic_context=StorySemanticContext(
            entities=[
                StoryEntity(
                    unit_id="HACKER",
                    semantic_name="white hacker",
                    entity_type="MAIN_CHARACTER",
                    role="PRIMARY",
                ),
                StoryEntity(
                    unit_id="IDEA",
                    semantic_name="thinking idea",
                    entity_type="ICON",
                    role="SUPPORTING",
                ),
            ],
        ),
    )


def test_story_semantic_activation_anchors_visual_to_spoken_phrase(tmp_path: Path) -> None:
    script = "الهاكر الأبيض يحاول يفكر بطريقة مختلفة"
    scene = SceneSource(
        id="scene-1",
        image_path=tmp_path / "scene.png",
        order=0,
        script_char_start=0,
        script_char_end=len(script) - 1,
        units=[
            {"unit_id": "HACKER", "type": "MAIN_CHARACTER", "role": "PRIMARY"},
            {"unit_id": "IDEA", "type": "ICON", "role": "SUPPORTING"},
        ],
    )
    package = PackageModel(
        root=tmp_path,
        package_id="test",
        scenes=[scene],
        script=script,
    )
    character = _asset(tmp_path, "character", "character")
    bulb = _asset(tmp_path, "bulb", "idea_icon")
    class QueryAwareScorer(_FakeSemanticScorer):
        def score(self, query: str, candidates: list[str]) -> tuple[list[float], bool]:
            # Joint assignment needs asset-specific evidence; an identical score
            # vector for every query falsely claims both objects mean the same thing.
            if "white hacker" in query:
                return [0.96 if text == "الهاكر الأبيض" else 0.1 for text in candidates], True
            return super().score(query, candidates)

    scorer = QueryAwareScorer({
        "يفكر": 0.94,
        "يفكر بطريقة": 0.86,
    })
    planner = SemanticActivationPlanner(scorer=scorer)
    result = planner.enrich(package, _transcript(), [character, bulb], [_beat()])[0]

    activations = {row.asset_id: row for row in result.asset_activations}
    assert activations["bulb"].policy == "SEMANTIC"
    assert activations["bulb"].trigger_text == "يفكر"
    assert activations["bulb"].spoken_start == pytest.approx(1.70)
    assert activations["bulb"].confidence == pytest.approx(0.94)


def test_motion_settles_semantic_asset_on_story_anchor() -> None:
    beat = _beat().model_copy(update={
        "asset_activations": [
            AssetActivation(
                asset_id="bulb",
                semantic_unit_id="IDEA",
                trigger_text="يفكر",
                spoken_start=1.70,
                spoken_end=1.92,
                confidence=0.94,
                source="multilingual_semantic_match",
                policy="SEMANTIC",
            )
        ],
    })
    composition = CompositionBeat(
        beat_id=beat.id,
        items=[
            LayoutItem(
                asset_id="character",
                x=0.30,
                y=0.50,
                width=0.30,
                height=0.55,
                z=1,
            ),
            LayoutItem(
                asset_id="bulb",
                x=0.70,
                y=0.38,
                width=0.18,
                height=0.18,
                z=2,
            ),
        ],
    )
    cues = MotionPlanner().plan([beat], [composition])
    bulb = next(cue for cue in cues if cue.asset_id == "bulb")

    assert bulb.params["semantic_settle_time"] == pytest.approx(1.70, abs=1e-6)
    assert bulb.start < 1.70 <= bulb.end


def test_low_confidence_semantics_abstain_instead_of_guessing(tmp_path: Path) -> None:
    script = "الهاكر الأبيض يحاول يفكر بطريقة مختلفة"
    scene = SceneSource(
        id="scene-1",
        image_path=tmp_path / "scene.png",
        order=0,
        script_char_start=0,
        script_char_end=len(script) - 1,
        units=[
            {"unit_id": "HACKER", "type": "MAIN_CHARACTER", "role": "PRIMARY"},
            {"unit_id": "IDEA", "type": "ICON", "role": "SUPPORTING"},
        ],
    )
    package = PackageModel(root=tmp_path, package_id="test", scenes=[scene], script=script)
    assets = [
        _asset(tmp_path, "character", "character"),
        _asset(tmp_path, "bulb", "unknown_icon"),
    ]
    planner = SemanticActivationPlanner(
        scorer=_FakeSemanticScorer({"يفكر": 0.51, "بطريقة": 0.50})
    )
    result = planner.enrich(package, _transcript(), assets, [_beat()])[0]
    by_asset = {row.asset_id: row for row in result.asset_activations}

    assert by_asset["bulb"].policy == "FALLBACK"
    assert by_asset["bulb"].spoken_start is None


def test_required_semantic_model_fails_closed_instead_of_lexical_downgrade(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scorer = HybridSemanticTextScorer("missing/test-model", required=True)

    def fail_load() -> None:
        raise RuntimeError("model unavailable")

    monkeypatch.setattr(scorer, "_load", fail_load)
    with pytest.raises(DependencyUnavailableError):
        scorer.score("thinking idea", ["يفكر", "مختلفة"])
