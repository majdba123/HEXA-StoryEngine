from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from app.canonical import (
    CanonicalAsset,
    CanonicalPackage,
    CanonicalScene,
    CanonicalScriptSpan,
    CanonicalSemanticEvent,
    CanonicalVisualLocator,
)
from app.choreography import ChoreographyDirector
from app.composition import CompositionPlanner
from app.models import Transcript, TranscriptWord, VisualAsset
from app.motion import MotionPlanner
from app.render import RenderPlanner
from app.shared.errors import StageFailedError
from app.story import StoryPlanner
from app.text import TextPlanner

_TOKENS = ("alpha", "beta", "gamma", "delta", "omega", "sigma", "theta", "kappa", "lambda", "zeta")


def _build_reused_carrier_case(
    root: Path,
    *,
    event_count: int,
    interval: float,
    ambiguous: bool = False,
) -> tuple[CanonicalPackage, Transcript, list[VisualAsset]]:
    scene_image = root / "scene.png"
    runtime_image = root / "runtime.png"
    Image.new("RGB", (1000, 1000), "white").save(scene_image)
    Image.new("RGBA", (180, 180), (40, 80, 180, 255)).save(runtime_image)

    tokens = _TOKENS[:event_count]
    script = " ".join(tokens)
    spans: list[tuple[str, int, int]] = []
    cursor = 0
    for token in tokens:
        spans.append((token, cursor, cursor + len(token)))
        cursor += len(token) + 1

    semantic = CanonicalAsset(
        unit_id="intent",
        asset_id="intent",
        scene_id="SCENE_001",
        script_text=script,
        script_span=CanonicalScriptSpan(
            text=script,
            global_char_start=0,
            global_char_end=len(script),
        ),
        visual_locator=CanonicalVisualLocator(cx=0.50, cy=0.50, width=0.40, height=0.40),
        confidence=1.0,
    )
    events = tuple(
        CanonicalSemanticEvent(
            semantic_event_id=f"E{index}",
            scene_id="SCENE_001",
            script_text=token,
            script_span=CanonicalScriptSpan(
                text=token,
                global_char_start=start,
                global_char_end=end,
            ),
            sequence_order=index,
            visual_leader_asset_id="intent",
            participant_asset_ids=("intent",),
            depends_on_event_ids=((f"E{index - 1}",) if index > 1 else ()),
        )
        for index, (token, start, end) in enumerate(spans, start=1)
    )
    scene = CanonicalScene(
        id="SCENE_001",
        image_path=scene_image,
        order=0,
        script_char_start=0,
        script_char_end=len(script) - 1,
        units=(semantic,),
        semantic_events=events,
    )
    package = CanonicalPackage(
        root=root,
        package_id=f"event-carrier-{event_count}-{interval}",
        script=script,
        scenes=(scene,),
        semantic_bindings_present=True,
    )

    words = [
        TranscriptWord(
            start=0.10 + index * interval,
            end=0.10 + index * interval + min(0.24, interval * 0.55),
            text=token,
            char_start=start,
            char_end=end,
        )
        for index, (token, start, end) in enumerate(spans)
    ]
    transcript = Transcript(
        duration=(words[-1].end + 0.25),
        segments=[],
        words=words,
        timing_source="forced_alignment",
    )

    assets = [
        VisualAsset(
            id="runtime-a",
            scene_id="SCENE_001",
            role="primary",
            image_path=runtime_image,
            extraction_method="test2-region-carrier",
            source_bbox=(340, 390, 160, 160) if ambiguous else (360, 360, 160, 160),
            source_canvas_width=1000,
            source_canvas_height=1000,
            source_area_ratio=0.0256,
            can_animate_independently=True,
            confidence=1.0,
        )
    ]
    if ambiguous:
        assets.append(VisualAsset(
            id="runtime-b",
            scene_id="SCENE_001",
            role="support",
            image_path=runtime_image,
            extraction_method="test2-region-carrier",
            source_bbox=(500, 390, 160, 160),
            source_canvas_width=1000,
            source_canvas_height=1000,
            source_area_ratio=0.0256,
            can_animate_independently=True,
            confidence=1.0,
        ))
    return package, transcript, assets


@pytest.mark.parametrize("event_count", [1, 2, 3, 5, 8, 10])
@pytest.mark.parametrize("interval", [0.40, 0.65, 0.95], ids=["fast", "normal", "slow"])
def test_region_carrier_semantics_survive_all_planning_layers(
    tmp_path: Path,
    event_count: int,
    interval: float,
) -> None:
    package, transcript, assets = _build_reused_carrier_case(
        tmp_path,
        event_count=event_count,
        interval=interval,
    )

    story = StoryPlanner().plan(package, transcript, assets)
    proxies = story[0].semantic_event_proxies
    assert len(proxies) == event_count
    assert [row.semantic_event_id for row in proxies] == [f"E{i}" for i in range(1, event_count + 1)]
    assert {row.asset_id for row in proxies} == {"runtime-a"}

    choreography = ChoreographyDirector().plan(package, story, assets)
    assert [flow.event_id for flow in choreography.directives[0].event_flows] == [
        f"E{i}" for i in range(1, event_count + 1)
    ]

    composition = CompositionPlanner().plan(story, assets, choreography)
    motion = MotionPlanner().plan(story, composition, choreography, assets)
    represented_motion_events = {
        segment.semantic_event_id
        for cue in motion
        for segment in cue.segments
        if segment.semantic_event_id
    }
    assert represented_motion_events == {f"E{i}" for i in range(1, event_count + 1)}

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


@pytest.mark.parametrize("event_count", [1, 3])
def test_ambiguous_region_carrier_fails_closed_at_story_boundary(
    tmp_path: Path,
    event_count: int,
) -> None:
    package, transcript, assets = _build_reused_carrier_case(
        tmp_path,
        event_count=event_count,
        interval=0.65,
        ambiguous=True,
    )
    with pytest.raises(StageFailedError) as exc_info:
        StoryPlanner().plan(package, transcript, assets)
    details = exc_info.value.details or {}
    assert details.get("code") == "FINAL_PACKAGE_SEMANTIC_EVENT_COVERAGE"
    assert details.get("missing_events")


@pytest.mark.parametrize("distractor_count", [0, 4, 9, 19])
def test_region_carrier_pipeline_survives_dense_scene_distractors(
    tmp_path: Path,
    distractor_count: int,
) -> None:
    package, transcript, assets = _build_reused_carrier_case(
        tmp_path,
        event_count=3,
        interval=0.65,
    )
    runtime_image = tmp_path / "runtime.png"
    for index in range(distractor_count):
        assets.append(VisualAsset(
            id=f"distractor-{index}",
            scene_id="SCENE_001",
            role="support",
            image_path=runtime_image,
            extraction_method="test2-region-carrier-distractor",
            source_bbox=(20 + (index % 5) * 90, 20 + (index // 5) * 75, 45, 45),
            source_canvas_width=1000,
            source_canvas_height=1000,
            source_area_ratio=0.002025,
            can_animate_independently=True,
            confidence=1.0,
        ))

    story = StoryPlanner().plan(package, transcript, assets)
    proxies = story[0].semantic_event_proxies
    assert [row.semantic_event_id for row in proxies] == ["E1", "E2", "E3"]
    assert {row.asset_id for row in proxies} == {"runtime-a"}

    choreography = ChoreographyDirector().plan(package, story, assets)
    composition = CompositionPlanner().plan(story, assets, choreography)
    motion = MotionPlanner().plan(story, composition, choreography, assets)
    represented = {
        segment.semantic_event_id
        for cue in motion
        for segment in cue.segments
        if segment.semantic_event_id
    }
    assert represented == {"E1", "E2", "E3"}
