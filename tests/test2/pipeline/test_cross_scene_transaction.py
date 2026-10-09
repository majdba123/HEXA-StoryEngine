"""Roadmap V2 Sprint 7 - continuity is one bounded Motion/Text/Boundary transaction.

Text is composed against final visual Motion and Boundary is planned on Motion + Text. A
continuity candidate is kept only where re-authoring both against it reproduces the certified
baseline exactly; otherwise that link abstains and the baseline cue is restored.
"""
from __future__ import annotations

from types import SimpleNamespace

from app.models import SceneBoundaryRelease, TextCue, TextPlan
from app.motion.cross_scene import ABSTAIN, HANDOFF_PARAM, CrossSceneContinuityPlanner
from app.pipeline import StoryEnginePipeline
from tests.test2.motion.test_cross_scene_continuity import SCENE, build, obj


def _pipeline(*, text_for, boundaries_for):
    pipeline = StoryEnginePipeline.__new__(StoryEnginePipeline)
    pipeline.cross_scene = CrossSceneContinuityPlanner()
    calls = {"text": 0, "boundary": 0}

    def compose(**kwargs):
        calls["text"] += 1
        return text_for(kwargs["motion"]), [], []

    def plan_boundaries(**kwargs):
        calls["boundary"] += 1
        return boundaries_for(kwargs["motion"])

    pipeline._compose_text_against_visual_motion = compose
    pipeline.scene_boundaries = SimpleNamespace(plan=plan_boundaries)
    pipeline.handoff_contracts = SimpleNamespace(require_motion_for_text_and_render=lambda **_: None)
    return pipeline, calls


def _run(pipeline, data, *, text, boundaries):
    package, story, composition, motion, assets, _ = data
    shared = SimpleNamespace(story=story, assets=assets, choreography=None, package=package,
                             transcript=SimpleNamespace(duration=SCENE * len(story)), text=text)
    target = SimpleNamespace(fps=30, width=1920, height=1080)
    return pipeline._cross_scene_transaction(
        shared=shared, target=target, composition=composition, motion=motion, text=text,
        text_composition=[], text_motion=[], scene_boundaries=boundaries)


def _data():
    return build([obj("A01", 0.30, 0.5, referent="REF_P")], [obj("B01", 0.33, 0.5, referent="REF_P")],
                 [obj("C01", 0.70, 0.2)])


BOUNDARIES = [SceneBoundaryRelease(beat_id="beat-002", from_beat_id="beat-001", mode="HARD_CUT", reason="r"),
              SceneBoundaryRelease(beat_id="beat-003", from_beat_id="beat-002", mode="EXACT_END", reason="r")]


def _continued(motion) -> bool:
    return any(HANDOFF_PARAM in cue.params for cue in motion)


def test_identical_re_authoring_keeps_the_candidate() -> None:
    pipeline, calls = _pipeline(text_for=lambda motion: TextPlan(), boundaries_for=lambda motion: list(BOUNDARIES))
    out = _run(pipeline, _data(), text=TextPlan(), boundaries=list(BOUNDARIES))
    assert _continued(out) and calls == {"text": 1, "boundary": 1}
    assert [d.accepted for d in pipeline.cross_scene.decisions] == [True]


def test_boundary_change_on_the_following_boundary_revokes_the_link() -> None:
    def boundaries_for(motion):
        rows = [row.model_copy(deep=True) for row in BOUNDARIES]
        if _continued(motion):  # the adapted cue would downgrade the NEXT release
            rows[1] = rows[1].model_copy(update={"mode": "HARD_CUT"})
        return rows

    pipeline, calls = _pipeline(text_for=lambda motion: TextPlan(), boundaries_for=boundaries_for)
    data = _data()
    out = _run(pipeline, data, text=TextPlan(), boundaries=list(BOUNDARIES))
    assert out == data[3] and not _continued(out)  # certified baseline cue restored
    [decision] = pipeline.cross_scene.decisions
    assert decision.decision == ABSTAIN and decision.reason == "transaction:text_or_boundary_would_change"
    assert calls == {"text": 1, "boundary": 1}  # no extra pass once nothing is left to verify


def test_text_change_revokes_the_link() -> None:
    moved = TextCue(id="t", beat_id="beat-002", text="w", semantic_type="K", source_char_start=0,
                    source_char_end=1, spoken_start=3.2, spoken_end=3.4, emphasis_time=3.3, style_id="s")
    pipeline, _ = _pipeline(text_for=lambda motion: TextPlan(cues=[moved]) if _continued(motion) else TextPlan(),
                            boundaries_for=lambda motion: list(BOUNDARIES))
    data = _data()
    out = _run(pipeline, data, text=TextPlan(), boundaries=list(BOUNDARIES))
    assert out == data[3]
    assert pipeline.cross_scene.decisions[0].decision == ABSTAIN


def test_no_referent_runs_no_transaction() -> None:
    pipeline, calls = _pipeline(text_for=lambda motion: TextPlan(), boundaries_for=lambda motion: list(BOUNDARIES))
    data = build([obj("A01", 0.30, 0.5)], [obj("B01", 0.33, 0.5)])
    out = _run(pipeline, data, text=TextPlan(), boundaries=list(BOUNDARIES))
    assert out is data[3] and calls == {"text": 0, "boundary": 0}
