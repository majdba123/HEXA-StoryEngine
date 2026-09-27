from __future__ import annotations

import pytest

from app.choreography import EventFlowStage
from app.models import LayoutItem
from app.motion import MotionPlanner
from app.motion.event_flow import MotionEventPhase
from app.motion.timing import projected_motion_activity_px, semantic_readability_floor_px
from app.shared.errors import StageFailedError


def _establish_phase() -> MotionEventPhase:
    return MotionEventPhase(
        event_id="E2",
        event_order=2,
        stage=EventFlowStage.ESTABLISH,
        step_index=0,
        involvement="FOCUS",
        focus_asset_id="carrier",
        source_asset_id=None,
        target_asset_id=None,
        result_asset_id=None,
        relationship=None,
        semantic_action=None,
        authority="FINAL_PACKAGE_DEPENDENCY_CARRIER_PROXY",
    )


@pytest.mark.parametrize(
    "duration",
    [0.20, 0.24919060675, 0.25, 0.30, 0.33, 0.50, 0.75, 1.0, 1.5, 3.0, 8.0],
)
@pytest.mark.parametrize(
    ("width", "height"),
    [
        (0.04, 0.04),
        (0.09, 0.16),
        (0.25, 0.25),
        (0.45, 0.18),
        (0.18, 0.45),
    ],
    ids=["tiny", "small-portrait", "square", "wide", "tall"],
)
def test_centered_establish_program_is_readable_and_comfort_feasible(
    duration: float,
    width: float,
    height: float,
) -> None:
    item = LayoutItem(
        asset_id="carrier", x=0.50, y=0.50, width=width, height=height
    )
    program = MotionPlanner._event_segment_program(
        phase=_establish_phase(),
        vector=(0.0, -1.0),
        item=item,
        focus_strength=0.70,
        energy=0.60,
        cohort_gain=1.0,
        duration=duration,
        semantic_peak_progress=0.5,
    )

    peak = max(
        program.keyframes,
        key=lambda frame: projected_motion_activity_px(
            dx=frame.dx,
            dy=frame.dy,
            scale=frame.scale,
            item_width=width,
            item_height=height,
        ),
    )
    achieved_px = projected_motion_activity_px(
        dx=peak.dx,
        dy=peak.dy,
        scale=peak.scale,
        item_width=width,
        item_height=height,
    )
    floor_px = semantic_readability_floor_px(
        "ESTABLISH",
        item_width=width,
        item_height=height,
        duration=duration,
    )
    assert achieved_px + 1e-6 >= floor_px
    assert program.keyframes[0].progress == 0.0
    assert program.keyframes[-1].progress == 1.0
    assert program.keyframes[-1].dx == pytest.approx(0.0)
    assert program.keyframes[-1].dy == pytest.approx(0.0)
    assert program.keyframes[-1].scale == pytest.approx(1.0)


@pytest.mark.parametrize(
    ("peak_progress", "expect_feasible"),
    [
        (0.55, True),
        (0.5609717764704252, True),
        (0.58, False),
    ],
    ids=["floor-below-ceiling", "floor-equals-ceiling", "floor-above-ceiling"],
)
def test_establish_readability_comfort_boundary_is_fail_closed(
    peak_progress: float,
    expect_feasible: bool,
) -> None:
    duration = 0.24919060675
    item = LayoutItem(
        asset_id="carrier", x=0.50, y=0.50, width=0.25, height=0.25
    )
    kwargs = dict(
        phase=_establish_phase(),
        item=item,
        dx=0.0,
        dy=-0.05,
        scale=1.0,
        duration=duration,
        readability_duration=duration,
        peak_progress=peak_progress,
    )
    if expect_feasible:
        MotionPlanner._enforce_event_readability(**kwargs)
        return

    with pytest.raises(StageFailedError) as exc_info:
        MotionPlanner._enforce_event_readability(**kwargs)
    details = exc_info.value.details or {}
    assert details.get("code") == "MOTION_INFEASIBLE_BEFORE_RENDER"
    assert details["readability_floor_px"] > details["translation_ceiling_px"]
    assert details["readability_floor_px"] > details["scale_ceiling_px"]
