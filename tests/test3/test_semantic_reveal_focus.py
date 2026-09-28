from __future__ import annotations

from pathlib import Path
import random
import statistics

import pytest

from app.motion.timing import story_activation_window
from app.story.windows import StoryAssetActivation
from tests.test2.motion.test_rhythm_regressions import _beat, _directive, _layout
from app.choreography.models import ChoreographyPlan
from app.motion import MotionPlanner
from tests.test3.test_semantic_persistence import (
    _assert_single_beat_renderer_lifecycle,
    _package_shape_pipeline,
    _single_beat_event_pipeline,
)


def _windows(story):
    return {
        row.asset_id: story_activation_window(row, story[0])[1]
        for row in story[0].asset_activations
        if story_activation_window(row, story[0])[1] is not None
    }


def _focus(motion):
    return {
        cue.asset_id: cue.params.get("semantic_focus", {})
        for cue in motion
    }


def assert_semantic_focus_progression(story, motion) -> None:
    windows = _windows(story)
    focus = _focus(motion)
    ordered = sorted(
        windows,
        key=lambda asset_id: (windows[asset_id].reveal_start, asset_id),
    )
    for asset_id in ordered:
        assert focus[asset_id]["active"] is True
        assert focus[asset_id]["cohort_gain"] > 0.0
        assert focus[asset_id]["semantic_event_id"]


def _assert_pipeline_timing(root: Path, assets: int, events: int, duration: float):
    story, choreography, _composition, motion, render_plan = _single_beat_event_pipeline(
        root,
        asset_count=assets,
        event_count=events,
        duration=duration,
    )
    assert render_plan.story == story
    assert render_plan.motion == motion
    assert len(choreography.directives[0].event_flows) == events
    windows = _windows(story)
    ordered = sorted(windows.values(), key=lambda row: row.reveal_start)
    assert all(
        left.reveal_start <= right.reveal_start
        for left, right in zip(ordered, ordered[1:])
    )
    _assert_single_beat_renderer_lifecycle(story, motion)
    assert_semantic_focus_progression(story, motion)
    return story, motion, windows


@pytest.mark.parametrize(
    "name,assets,events,duration",
    [
        ("well-spaced", 3, 3, 6.0),
        ("close-close-late", 3, 3, 9.0),
        ("no-front-loading", 4, 4, 9.0),
        ("sequential", 4, 4, 5.0),
        ("unrelated", 4, 4, 5.0),
        ("focus-transfer", 3, 3, 4.0),
        ("result-payoff", 3, 3, 4.0),
        ("presenter-icon", 2, 2, 3.0),
        ("dense", 20, 10, 12.0),
        ("short", 3, 3, 0.8),
        ("long", 8, 8, 12.0),
        ("one-asset", 1, 1, 6.0),
        ("completed-hold", 2, 2, 12.0),
        ("one-beat-multi-event", 3, 5, 6.0),
    ],
)
def test_focused_real_pipeline_reveal_and_focus(
    tmp_path: Path, name: str, assets: int, events: int, duration: float
) -> None:
    story, _motion, windows = _assert_pipeline_timing(
        tmp_path / name, assets, events, duration
    )
    anchors = {
        row.asset_id: row.spoken_start
        for row in story[0].asset_activations
        if row.asset_id in windows
    }
    assert all(
        windows[asset_id].reveal_start == pytest.approx(anchor)
        for asset_id, anchor in anchors.items()
    )
    if len(windows) > 1:
        last = max(row.reveal_start for row in windows.values())
        assert last >= min(anchors.values())


def test_same_event_assets_are_a_bounded_focus_cohort(tmp_path: Path) -> None:
    story, motion, windows = _assert_pipeline_timing(
        tmp_path / "same-event", 3, 2, 5.0
    )
    assert windows["asset-1"].reveal_start == pytest.approx(
        windows["asset-2"].reveal_start
    )
    focus = _focus(motion)
    gains = sorted(
        [focus["asset-1"]["cohort_gain"], focus["asset-2"]["cohort_gain"]],
        reverse=True,
    )
    assert gains[0] == pytest.approx(1.0)
    assert gains[1] < gains[0]
    _assert_single_beat_renderer_lifecycle(story, motion)


def test_unrelated_events_follow_spoken_time_not_dependency_edges(tmp_path: Path) -> None:
    story, _choreography, _composition, motion, _render_plan = (
        _single_beat_event_pipeline(
            tmp_path / "unrelated-events",
            asset_count=4,
            event_count=4,
            duration=8.0,
            unrelated=True,
        )
    )
    windows = _windows(story)
    assert [windows[f"asset-{index}"].reveal_start for index in range(4)] == sorted(
        windows[f"asset-{index}"].reveal_start for index in range(4)
    )
    assert_semantic_focus_progression(story, motion)


def test_safe_abstention_has_no_reveal_or_semantic_focus() -> None:
    row = StoryAssetActivation(
        asset_id="abstain",
        semantic_unit_id="abstain",
        semantic_event_id="E-safe",
        confidence=0.0,
        source="semantic_abstention",
        policy="FALLBACK",
        activation_policy="SAFE_ABSTENTION",
    )
    has_v2, window = story_activation_window(row, None)
    assert has_v2 is True
    assert window is None
    assert row.reveal_start is None

    beat = _beat(
        "safe-abstention",
        start=0.0,
        end=1.0,
        narration="unresolved visual",
        activations=[row],
        primary=["abstain"],
    )
    cues = MotionPlanner().plan(
        [beat],
        [_layout(beat.id, ["abstain"])],
        ChoreographyPlan(directives=(_directive(beat.id, primary="abstain"),)),
    )
    focus = cues[0].params["semantic_focus"]
    assert focus["active"] is False
    assert focus["cohort_gain"] == pytest.approx(0.0)
    assert focus["cohort_role"] == "abstention"


def test_400_generated_semantic_windows_preserve_anchor_order() -> None:
    rng = random.Random(0x5EAA17C)
    errors: list[float] = []
    for case in range(400):
        duration = rng.uniform(0.5, 12.0)
        count = rng.randint(1, 20)
        anchors = sorted(rng.uniform(0.0, duration * 0.92) for _ in range(count))
        rows = [
            StoryAssetActivation(
                asset_id=f"case-{case}-asset-{index}",
                semantic_unit_id=f"unit-{index}",
                semantic_event_id=f"event-{index}",
                semantic_event_order=index + 1,
                phrase_start=anchor,
                phrase_end=min(duration, anchor + 0.08),
                reveal_start=anchor,
                semantic_peak=min(duration, anchor + 0.04),
                settle_at=min(duration, anchor + 0.08),
                activation_policy="OWN_WINDOW",
            )
            for index, anchor in enumerate(anchors)
        ]
        reveals = [row.reveal_start for row in rows]
        assert reveals == sorted(reveals)
        errors.extend(abs(row.reveal_start - anchor) for row, anchor in zip(rows, anchors))
        assert all(row.settle_at <= duration for row in rows)
    assert len(errors) >= 400
    assert max(errors) == pytest.approx(0.0)
    assert statistics.median(errors) == pytest.approx(0.0)


@pytest.mark.parametrize(
    "scene_count,event_count",
    [(35, 2), (40, 2), (35, 3), (40, 3)],
)
def test_package_shaped_reveal_focus_stress(
    tmp_path: Path, scene_count: int, event_count: int
) -> None:
    story, choreography, motion, render_plan = _package_shape_pipeline(
        tmp_path / f"sprint2-{scene_count}-{event_count}",
        scene_count=scene_count,
        event_count=event_count,
    )
    assert len(story) == scene_count
    assert len(choreography.directives) == scene_count
    assert render_plan.motion == motion
    for beat in story:
        assert all(
            activation.activation_policy != "SAFE_ABSTENTION"
            for activation in beat.asset_activations
            if activation.asset_id in (beat.active_visual_semantic_state or {})
        )


def test_shared_planners_are_package_local(tmp_path: Path) -> None:
    from app.choreography import ChoreographyDirector
    from app.composition import CompositionPlanner
    from app.motion import MotionPlanner
    from app.story import StoryPlanner

    planners = (StoryPlanner(), ChoreographyDirector(), CompositionPlanner(), MotionPlanner())

    def run(name: str, assets: int, events: int):
        story, _choreography, _composition, motion, _render = _single_beat_event_pipeline(
            tmp_path / name,
            asset_count=assets,
            event_count=events,
            duration=6.0,
            planners=planners,
        )
        return story, motion

    a1 = run("a1", 3, 3)
    b1 = run("b1", 8, 5)
    b2 = run("b2", 8, 5)
    a2 = run("a2", 3, 3)
    assert [row.model_dump(exclude={"id"}) for row in a1[0]] == [
        row.model_dump(exclude={"id"}) for row in a2[0]
    ]
    assert [row.model_dump(exclude={"beat_id"}) for row in b1[1]] == [
        row.model_dump(exclude={"beat_id"}) for row in b2[1]
    ]
