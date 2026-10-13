"""Pre-Motion audit of authored leader reading time."""

from app.models import StoryBeat, StoryEventAuthority
from app.motion.rhythm import RhythmDecision, audit_leader_read_holds
from app.story.windows import StoryAssetActivation


def _beat(*, settle: float, end: float, leader: str = "camera") -> StoryBeat:
    activation = StoryAssetActivation(
        asset_id=leader, spoken_start=1.0, spoken_end=end,
        source="unified_final_package", policy="EXPLICIT",
        sequence_order=3, group_animation_policy="SEQUENTIAL_WITHIN_PHRASE",
        phrase_start=1.1, phrase_end=settle, reveal_start=1.1,
        semantic_peak=(1.1 + settle) / 2, settle_at=settle,
        activation_policy="OWN_WINDOW",
    ).with_legacy_evidence()
    return StoryBeat(
        id="beat", scene_id="scene", start=0.0, end=end,
        narration="a short spoken phrase", action="REVEAL",
        asset_activations=[activation],
        event_authorities=[StoryEventAuthority(event_id="event", leader_asset_ids=[leader])],
    )


def _decision() -> RhythmDecision:
    return RhythmDecision("balanced", "balanced", 0.3, 0.1, 1, "test")


def test_final_authored_leader_is_reported_before_motion() -> None:
    row = audit_leader_read_holds([_beat(settle=1.4, end=1.4)], {"beat": _decision()})[0]
    assert row["diagnosis"] == "AUTHORED_LEADER_READ_HOLD_INFEASIBLE"
    assert row["available_scene_local_hold_ms"] == 0
    assert row["shortfall_ms"] == 300
    assert row["sequence_order"] == 3
    assert row["group_animation_policy"] == "SEQUENTIAL_WITHIN_PHRASE"


def test_roomy_or_ambiguous_event_does_not_invent_a_timing_conflict() -> None:
    roomy = _beat(settle=1.3, end=1.7)
    ambiguous = _beat(settle=1.4, end=1.4).model_copy(update={
        "event_authorities": [StoryEventAuthority(event_id="event", leader_asset_ids=["a", "b"])]})
    assert audit_leader_read_holds([roomy, ambiguous], {"beat": _decision()}) == []


def test_unique_result_is_audited_when_causal_leader_is_different() -> None:
    beat = _beat(settle=1.4, end=1.4)
    beat = beat.model_copy(update={"event_authorities": [StoryEventAuthority(
        event_id="event", leader_asset_ids=["cause"], result_asset_ids=["camera"],
    )]})
    rows = audit_leader_read_holds([beat], {"beat": _decision()})
    assert len(rows) == 1
    assert rows[0]["leader_asset_id"] == "camera"
