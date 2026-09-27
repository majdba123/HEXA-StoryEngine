from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.composition.text_director import TextPlacementDirector
from app.models import TextCompositionBeat, TextCue, TextLayoutItem, TextPlan
from app.pipeline import StoryEnginePipeline
from app.shared.errors import StageFailedError


def _cue(cue_id: str, priority: int) -> TextCue:
    return TextCue(
        id=cue_id,
        beat_id="beat-001",
        text=cue_id,
        semantic_type="keyword",
        source_char_start=0,
        source_char_end=1,
        spoken_start=0.1,
        spoken_end=0.3,
        emphasis_time=0.1,
        priority=priority,
        style_id="keyword",
    )


class _PrimaryTextComposition:
    def __init__(self, accepted_ids: set[str]) -> None:
        self.accepted_ids = accepted_ids
        self.visual_motion = None
        self.calls = 0

    def plan(self, *_args, text_cues=None, visual_motion=None, **_kwargs):
        self.calls += 1
        self.visual_motion = visual_motion
        cues = text_cues if text_cues is not None else _args[2]
        items = [
            TextLayoutItem(text_cue_id=cue.id, x=0.5, y=0.5, max_width=0.3)
            for cue in cues
            if cue.id in self.accepted_ids
        ]
        return [TextCompositionBeat(beat_id="beat-001", items=items)] if items else []


class _CaptureTextMotion:
    def __init__(self) -> None:
        self.visual_motion = None
        self.cue_ids: list[str] = []

    def plan(self, _story, cues, _composition, _choreography, *, visual_motion=None):
        self.visual_motion = visual_motion
        self.cue_ids = [cue.id for cue in cues]
        return ["text-motion"] if cues else []


def _pipeline(*, accepted_ids: set[str], require_text: bool) -> StoryEnginePipeline:
    pipeline = StoryEnginePipeline.__new__(StoryEnginePipeline)
    pipeline.settings = SimpleNamespace(require_text_layer=require_text)
    pipeline.text_composition = _PrimaryTextComposition(accepted_ids)
    pipeline.text_motion = _CaptureTextMotion()
    return pipeline


def test_primary_text_authoring_consumes_final_visual_motion_once() -> None:
    pipeline = _pipeline(accepted_ids={"text-a"}, require_text=False)
    motion = [SimpleNamespace(asset_id="hero")]
    text = TextPlan(cues=[_cue("text-a", 90)], styles=[])

    accepted, composition, text_motion = pipeline._compose_text_against_visual_motion(
        story=[], composition=[], motion=motion, text=text, assets=[], choreography=[]
    )

    assert [cue.id for cue in accepted.cues] == ["text-a"]
    assert composition[0].items[0].text_cue_id == "text-a"
    assert text_motion == ["text-motion"]
    assert pipeline.text_composition.calls == 1
    assert pipeline.text_composition.visual_motion is motion
    assert pipeline.text_motion.visual_motion is motion


def test_unsafe_optional_text_is_excluded_from_every_final_text_structure() -> None:
    pipeline = _pipeline(accepted_ids={"strong"}, require_text=False)
    text = TextPlan(cues=[_cue("weak", 60), _cue("strong", 95)], styles=[])

    accepted, composition, _ = pipeline._compose_text_against_visual_motion(
        story=[], composition=[], motion=[], text=text, assets=[], choreography=[]
    )

    assert [cue.id for cue in accepted.cues] == ["strong"]
    assert [item.text_cue_id for item in composition[0].items] == ["strong"]
    assert pipeline.text_motion.cue_ids == ["strong"]


def test_required_unsafe_text_fails_closed_during_primary_authoring() -> None:
    pipeline = _pipeline(accepted_ids=set(), require_text=True)
    text = TextPlan(cues=[_cue("required", 90)], styles=[])

    with pytest.raises(StageFailedError) as caught:
        pipeline._compose_text_against_visual_motion(
            story=[], composition=[], motion=[], text=text, assets=[], choreography=[]
        )

    assert caught.value.effective_code == "TEXT_LAYOUT_REFERENCE_VIOLATION"
    assert caught.value.details["text_cue_ids"] == ["required"]


def test_higher_priority_simultaneous_text_is_the_accepted_primary_cue() -> None:
    pipeline = _pipeline(accepted_ids={"high"}, require_text=False)
    text = TextPlan(cues=[_cue("low", 50), _cue("high", 95)], styles=[])

    accepted, _, _ = pipeline._compose_text_against_visual_motion(
        story=[], composition=[], motion=[], text=text, assets=[], choreography=[]
    )

    assert [cue.id for cue in accepted.cues] == ["high"]


def test_primary_typography_ladder_includes_absolute_model_floor() -> None:
    scales = TextPlacementDirector._font_scales(_cue("text-a", 90))
    assert scales[0] == 1.0
    assert scales[-1] == 0.50
    assert min(scales) == 0.50
