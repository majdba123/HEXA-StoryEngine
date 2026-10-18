"""Regressions for NO_RELATION_OVERLAP after the final VP3 read-hold pass.

These cases exercise the original failure boundary using real MotionCue/StoryBeat
contracts. No Final Package sidecar, user media, or production state is needed.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.choreography.models import InteractionIntent
from app.models import AssetActivation, LayoutItem, MotionCue, MotionSegment, StoryBeat
from app.motion.planner import MotionPlanner
from app.motion.read_hold import reserve_scene_read_hold
from app.motion.rhythm import MIN_FOCUS_OVERLAP_SECONDS
from app.shared.errors import StageFailedError


PROGRAM = {
    "name": "semantic_accent",
    "keyframes": [
        {"progress": 0.0, "dx": 0.0, "dy": 0.0, "scale": 1.0},
        {"progress": 0.45, "dx": 0.03, "dy": 0.0, "scale": 1.0},
        {"progress": 1.0, "dx": 0.0, "dy": 0.0, "scale": 1.0},
    ],
}


def _cue(
    asset: str,
    phase: str,
    start: float,
    end: float,
    *,
    source: str = "source",
    target: str = "target",
    event_id: str = "E1",
    relationship: str = "ENABLES",
) -> MotionCue:
    segment = MotionSegment(
        phase=phase,
        start=start,
        end=end,
        program=dict(PROGRAM),
        involvement="SOURCE" if phase == "INTERACT" else "TARGET",
        source_asset_id=source,
        target_asset_id=target,
        semantic_event_id=event_id,
        semantic_action="TRAVEL",
        relationship=relationship,
        handoff_deadline=end,
    )
    return MotionCue(
        beat_id="B1", asset_id=asset, kind="program_v3", start=0.2, end=1.99,
        segments=[segment],
    )


def _beat(*, sequential: bool = False) -> StoryBeat:
    return StoryBeat(
        id="B1", scene_id="S1", start=0.0, end=2.0, narration="story",
        action="TRAVEL",
        asset_activations=[
            AssetActivation(
                asset_id="source", semantic_event_id="E1", semantic_event_order=1,
            ),
            AssetActivation(
                asset_id="target", semantic_event_id="E2" if sequential else "E1",
                semantic_event_order=2 if sequential else 1,
            ),
        ],
    )


def _items(*ids: str) -> dict[str, LayoutItem]:
    return {
        asset_id: LayoutItem(
            asset_id=asset_id, x=0.15 + index * 0.22, y=0.5,
            width=0.2, height=0.3,
        )
        for index, asset_id in enumerate(ids)
    }


def _directive(*sources: str) -> SimpleNamespace:
    return SimpleNamespace(event_flows=(
        SimpleNamespace(interactions=tuple(
            InteractionIntent(
                semantic_action="TRAVEL", relationship="ENABLES",
                subject_asset_id=source, object_asset_id="target",
                authority="FINAL_PACKAGE_ASSET_RELATION", executable=True,
            )
            for source in sources
        )),
    ))


def _assert_contract(cues: list[MotionCue], beat: StoryBeat, *sources: str) -> None:
    MotionPlanner._assert_authored_relation_contract(
        cues, beat=beat, directive=_directive(*sources)
    )


def test_read_hold_does_not_break_a_previously_valid_causal_pair() -> None:
    """Original regression: source shrinks to 1.70 while REACT starts at 1.72."""
    beat = _beat()
    source = _cue("source", "INTERACT", 1.30, 1.95)
    target = _cue("target", "REACT", 1.72, 1.95)
    _assert_contract([source, target], beat, "source")

    # A per-asset/old-style hold has no view of the paired semantic relation.
    individually_trimmed = (
        reserve_scene_read_hold([source], beat=beat, hold=0.30, items=_items("source")) +
        reserve_scene_read_hold([target], beat=beat, hold=0.30, items=_items("target"))
    )
    with pytest.raises(StageFailedError, match="could not preserve causal relation overlap"):
        _assert_contract(individually_trimmed, beat, "source")

    combined = reserve_scene_read_hold(
        [source, target], beat=beat, hold=0.30, items=_items("source", "target")
    )
    _assert_contract(combined, beat, "source")
    interact, react = combined[0].segments[0], combined[1].segments[0]
    assert min(interact.end, react.end) - max(interact.start, react.start) >= (
        MIN_FOCUS_OVERLAP_SECONDS - 1e-8
    )
    assert interact.end <= source.segments[0].end
    assert interact.start == source.segments[0].start
    assert react.start == target.segments[0].start
    assert combined[0].params["read_hold"][0]["decision"] == (
        "causal_relation_overlap_priority"
    )
    assert (combined[0].start, combined[0].end) == (source.start, source.end)


def test_ordered_later_event_is_not_forced_to_overlap() -> None:
    beat = _beat(sequential=True)
    source = _cue("source", "INTERACT", 1.30, 1.95)
    target = _cue("target", "REACT", 1.72, 1.95)
    out = reserve_scene_read_hold(
        [source, target], beat=beat, hold=0.30, items=_items("source", "target")
    )
    assert out[0].segments[0].end == pytest.approx(1.70)
    assert out[0].params["read_hold"][0]["decision"] == "finished_before_read_hold"
    _assert_contract(out, beat, "source")  # The authored sequential exception.


def test_mismatched_relation_identity_does_not_protect_unrelated_motion() -> None:
    beat = _beat()
    source = _cue("source", "INTERACT", 1.30, 1.95)
    target = _cue("target", "REACT", 1.72, 1.95, relationship="ATTACKS")
    out = reserve_scene_read_hold(
        [source, target], beat=beat, hold=0.30, items=_items("source", "target")
    )
    assert out[0].segments[0].end == pytest.approx(1.70)
    assert out[0].params["read_hold"][0]["decision"] == "finished_before_read_hold"


def test_preexisting_story_timing_contradiction_still_fails_closed() -> None:
    beat = _beat()
    source = _cue("source", "INTERACT", 1.30, 1.60)
    target = _cue("target", "REACT", 1.72, 1.95)
    out = reserve_scene_read_hold(
        [source, target], beat=beat, hold=0.30, items=_items("source", "target")
    )
    assert out[0].segments[0].end == source.segments[0].end
    with pytest.raises(StageFailedError, match="could not preserve causal relation overlap"):
        _assert_contract(out, beat, "source")


def test_only_existing_overlap_is_protected_when_narrower_than_two_frames() -> None:
    beat = _beat()
    source = _cue("source", "INTERACT", 1.30, 1.73)
    target = _cue("target", "REACT", 1.72, 1.95)
    out = reserve_scene_read_hold(
        [source, target], beat=beat, hold=0.30, items=_items("source", "target")
    )
    assert out[0].segments[0].end == pytest.approx(1.73)
    _assert_contract(out, beat, "source")


def test_one_target_reacting_to_multiple_authored_sources_stays_valid() -> None:
    beat = _beat()
    sources = [
        _cue("source", "INTERACT", 1.30, 1.95),
        _cue("other", "INTERACT", 1.42, 1.93, source="other"),
    ]
    beat.asset_activations.append(
        AssetActivation(asset_id="other", semantic_event_id="E1", semantic_event_order=1)
    )
    target = _cue("target", "REACT", 1.72, 1.95)
    target.segments.append(
        _cue("target", "REACT", 1.74, 1.95, source="other").segments[0]
    )
    out = reserve_scene_read_hold(
        [*sources, target], beat=beat, hold=0.30,
        items=_items("source", "other", "target"),
    )
    _assert_contract(out, beat, "source", "other")
    for source in out[:2]:
        reaction = next(
            segment for segment in out[2].segments
            if segment.source_asset_id == source.asset_id
        )
        assert min(source.segments[0].end, reaction.end) > max(
            source.segments[0].start, reaction.start
        )


def test_unrelated_read_hold_behavior_remains_unchanged() -> None:
    beat = _beat()
    cue = _cue("source", "INTERACT", 1.30, 1.95)
    out = reserve_scene_read_hold(
        [cue], beat=beat, hold=0.30, items=_items("source")
    )[0]
    assert out.segments[0].end == pytest.approx(1.70)
    assert out.params["read_hold"][0]["decision"] == "finished_before_read_hold"
