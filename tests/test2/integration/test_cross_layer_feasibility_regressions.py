from __future__ import annotations

from pathlib import Path

import pytest

from app.choreography import ChoreographyDirector
from app.composition import CompositionPlanner
from app.motion import MotionPlanner
from app.render import RenderPlanner
from app.story import StoryPlanner
from app.text import TextPlanner
from tests.test2.integration.test_event_carrier_pipeline_regressions import (
    _build_reused_carrier_case,
)


@pytest.mark.parametrize(
    ("tail_padding", "expected_duration"),
    [
        (0.101, 0.200),
        (0.15019060675, 0.24919060675),
        (0.151, 0.250),
        (0.201, 0.300),
    ],
    ids=["200ms", "diagnostic-249ms", "250ms", "300ms"],
)
def test_short_dependency_proxy_contract_is_executable_through_motion(
    tmp_path: Path,
    tail_padding: float,
    expected_duration: float,
) -> None:
    package, transcript, assets = _build_reused_carrier_case(
        tmp_path,
        event_count=2,
        interval=0.18,
    )
    transcript = transcript.model_copy(
        update={"duration": transcript.words[-1].end + tail_padding}
    )

    story = StoryPlanner().plan(package, transcript, assets)
    proxies = story[0].semantic_event_proxies
    assert [row.semantic_event_id for row in proxies] == ["E1", "E2"]
    short_proxy = proxies[-1]
    duration = short_proxy.settle_at - short_proxy.reveal_start
    assert duration == pytest.approx(expected_duration, abs=1e-9)
    assert short_proxy.semantic_peak == pytest.approx(
        short_proxy.reveal_start + duration * 0.5,
        abs=1e-9,
    )

    choreography = ChoreographyDirector().plan(package, story, assets)
    flows = {row.event_id: row for row in choreography.directives[0].event_flows}
    assert flows["E2"].dependency_ids == ("E1",)

    composition = CompositionPlanner().plan(story, assets, choreography)
    assert {item.asset_id for item in composition[0].items} == {"runtime-a"}
    motion = MotionPlanner().plan(story, composition, choreography, assets)

    segment = next(
        row
        for cue in motion
        for row in cue.segments
        if row.semantic_event_id == "E2" and row.phase == "ESTABLISH"
    )
    assert segment.end - segment.start == pytest.approx(expected_duration, abs=1e-9)
    assert segment.program["semantic_peak_progress"] == pytest.approx(0.5, abs=1e-9)

    text = TextPlanner().plan(
        transcript=transcript,
        story=story,
        assets=assets,
        package=package,
        choreography=choreography,
    )
    render_workspace = tmp_path / "render"
    render_workspace.mkdir()
    render_plan, render_path = RenderPlanner().compile(
        transcript=transcript,
        assets=assets,
        story=story,
        composition=composition,
        motion=motion,
        workspace=render_workspace,
        text=text,
    )
    assert render_path.is_file()
    assert render_plan.story == story
    assert render_plan.motion == motion
