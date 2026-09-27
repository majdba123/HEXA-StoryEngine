from __future__ import annotations

from app.choreography import EventFlowStage
from app.motion.event_flow import MotionEventPhase
from app.motion.planner import MotionPlanner
from app.models import MotionCue, StoryBeat


def test_cross_event_reaction_uses_proxy_visible_time_before_owner_cue() -> None:
    phase = MotionEventPhase(
        event_id="E1",
        event_order=1,
        stage=EventFlowStage.REACT,
        step_index=1,
        involvement="TARGET",
        focus_asset_id="target",
        source_asset_id="source",
        target_asset_id="target",
        result_asset_id=None,
        relationship="ENABLES",
        semantic_action="CONNECT",
        authority="FINAL_PACKAGE_ASSET_RELATION",
        spoken_start=7.02,
        spoken_end=7.72,
    )
    cue = MotionCue(
        beat_id="beat",
        asset_id="target",
        kind="program_v3",
        start=7.8504,
        end=8.33,
    )
    beat = StoryBeat(
        id="beat",
        scene_id="scene",
        start=7.0,
        end=10.5,
        narration="source target",
        primary_asset_ids=["source"],
        support_asset_ids=["target"],
        action="EXPLAIN",
    )

    window = MotionPlanner._event_segment_window(
        phase=phase,
        activation=None,
        cue=cue,
        beat=beat,
        deadline=10.5,
        relation_source_start=7.02,
        motion_ready_start=7.44,
        semantic_peak_target=None,
        align_to_peak=False,
    )

    assert window is not None
    assert window[0] >= 7.44 - 1e-6
    assert window[1] <= 7.72 + 1e-9
    assert window[1] - window[0] >= 0.06
