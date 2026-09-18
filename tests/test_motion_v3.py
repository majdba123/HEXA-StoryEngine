from __future__ import annotations

import pytest

from app.models import CompositionBeat, LayoutItem, StoryBeat
from app.motion import MotionPlanner
from app.motion.easing import sample_easing
from app.motion.timing import MotionTimingPolicy


def _beat(
    *,
    beat_id: str = "beat-001",
    action: str = "INTRODUCE",
    narration: str = "clear explanation",
    start: float = 0.0,
    end: float = 2.0,
    audio_start: float = 0.24,
    audio_end: float = 1.8,
) -> StoryBeat:
    return StoryBeat(
        id=beat_id,
        scene_id="scene-001",
        start=start,
        end=end,
        audio_start=audio_start,
        audio_end=audio_end,
        narration=narration,
        primary_asset_ids=["primary"],
        support_asset_ids=["support"],
        action=action,
    )


def _composition(beat_id: str = "beat-001") -> CompositionBeat:
    return CompositionBeat(
        beat_id=beat_id,
        items=[
            LayoutItem(asset_id="primary", x=0.28, y=0.52, width=0.36, height=0.48, z=20),
            LayoutItem(asset_id="support", x=0.72, y=0.50, width=0.25, height=0.30, z=15),
        ],
    )


def test_motion_v3_is_backend_neutral_and_does_not_mutate_composition() -> None:
    beat = _beat(action="HANDOFF")
    composition = _composition()
    original = composition.model_dump()

    cues = MotionPlanner().plan([beat], [composition])

    assert composition.model_dump() == original
    assert len(cues) == 2
    assert all(cue.kind == "program_v3" for cue in cues)
    assert all(cue.params["engine_version"] == 3 for cue in cues)

    for cue in cues:
        keyframes = cue.params["program"]["keyframes"]
        assert keyframes[0]["progress"] == 0.0
        assert keyframes[-1]["progress"] == 1.0
        assert keyframes[-1]["dx"] == pytest.approx(0.0)
        assert keyframes[-1]["dy"] == pytest.approx(0.0)
        assert cue.start >= beat.start
        assert cue.end <= beat.end

    assert cues[1].start > cues[0].start


def test_result_program_contains_a_real_reaction_not_only_an_entrance() -> None:
    cues = MotionPlanner().plan([_beat(action="RESULT")], [_composition()])
    primary = cues[0]
    keyframes = primary.params["program"]["keyframes"]

    assert primary.params["program"]["name"] == "result_impact"
    assert len(keyframes) >= 5
    dx_values = [frame["dx"] for frame in keyframes]
    assert min(dx_values) < 0 < max(dx_values)


def test_fast_speech_compresses_motion_duration() -> None:
    policy = MotionTimingPolicy()
    slow = _beat(narration="two words")
    fast = _beat(narration="one two three four five six seven eight nine ten eleven twelve")

    slow_window = policy.window(beat=slow, distance=0.05, index=0, count=1, primary=True)
    fast_window = policy.window(beat=fast, distance=0.05, index=0, count=1, primary=True)

    assert fast_window.duration < slow_window.duration


@pytest.mark.parametrize(
    ("name", "expected_mid"),
    [
        ("linear", 0.5),
        ("smoothstep", 0.5),
        ("ease_in_out_cubic", 0.5),
    ],
)
def test_standard_easing_boundaries(name: str, expected_mid: float) -> None:
    assert sample_easing(name, 0.0) == pytest.approx(0.0)
    assert sample_easing(name, 0.5) == pytest.approx(expected_mid)
    assert sample_easing(name, 1.0) == pytest.approx(1.0)


def test_choreography_reject_creates_meaningful_interaction_and_scale_reaction() -> None:
    from pathlib import Path
    from app.choreography import ChoreographyDirector
    from app.models import PackageModel, SceneSource

    beat = _beat(action="REVEAL_DETAIL")
    package = PackageModel(
        root=Path("/tmp"), package_id="p", script="x",
        scenes=[SceneSource(
            id="scene-001", image_path=Path("/scene.png"), order=1,
            units=[{"semantic_name":"subsequent_decline","narrative_function":"EXPLAIN_SUBSEQUENT_DECLINE"}],
        )],
    )
    choreography = ChoreographyDirector().plan(package, [beat], [])
    cue = MotionPlanner().plan([beat], [_composition()], choreography)[0]
    keyframes = cue.params["program"]["keyframes"]

    assert cue.params["choreography"]["action"] == "REJECT"
    assert cue.params["program"]["name"] == "reject_attempt_recoil"
    assert max(abs(frame["dx"]) + abs(frame["dy"]) for frame in keyframes) > 0.04
    assert max(frame["scale"] for frame in keyframes) >= 1.05
    assert min(frame["scale"] for frame in keyframes) < 1.0


def test_semantic_handoff_begins_from_previous_focal_position() -> None:
    from pathlib import Path
    from app.choreography import ChoreographyDirector
    from app.models import PackageModel, SceneSource

    first = _beat(beat_id="beat-001", start=0.0, end=1.8, audio_start=0.2, audio_end=1.6)
    first.primary_asset_ids = ["old"]
    first.support_asset_ids = []
    second = _beat(beat_id="beat-002", start=1.8, end=3.8, audio_start=2.0, audio_end=3.5)
    second.scene_id = "scene-002"
    second.primary_asset_ids = ["new"]
    second.support_asset_ids = []
    package = PackageModel(
        root=Path("/tmp"), package_id="p", script="x",
        scenes=[
            SceneSource(id="scene-001", image_path=Path("/a.png"), order=1, units=[]),
            SceneSource(id="scene-002", image_path=Path("/b.png"), order=2, units=[]),
        ],
    )
    composition = [
        CompositionBeat(beat_id=first.id, items=[LayoutItem(asset_id="old", x=0.25, y=0.50, width=0.30, height=0.40)]),
        CompositionBeat(beat_id=second.id, items=[LayoutItem(asset_id="new", x=0.70, y=0.55, width=0.32, height=0.42)]),
    ]
    choreography = ChoreographyDirector().plan(package, [first, second], [])
    cue = [c for c in MotionPlanner().plan([first, second], composition, choreography) if c.beat_id == second.id][0]
    program = cue.params["program"]

    assert program["name"].startswith("handoff_then_")
    assert program["keyframes"][0]["dx"] < -0.20
    assert program["keyframes"][0]["scale"] == pytest.approx(0.80)


def test_semantic_handoff_keeps_reject_action_after_arrival() -> None:
    from pathlib import Path
    from app.choreography import ChoreographyDirector
    from app.models import PackageModel, SceneSource, VisualAsset

    first = _beat(beat_id="beat-001", start=0.0, end=1.8, audio_start=0.2, audio_end=1.6)
    first.primary_asset_ids = ["old"]
    first.support_asset_ids = []
    second = _beat(beat_id="beat-002", start=1.8, end=3.8, audio_start=2.0, audio_end=3.5)
    second.scene_id = "scene-002"
    second.primary_asset_ids = ["new"]
    second.support_asset_ids = ["target"]
    package = PackageModel(
        root=Path("/tmp"), package_id="p", script="x",
        scenes=[
            SceneSource(id="scene-001", image_path=Path("/a.png"), order=1, units=[]),
            SceneSource(
                id="scene-002", image_path=Path("/b.png"), order=2,
                units=[{"semantic_name": "subsequent_decline", "narrative_function": "EXPLAIN_SUBSEQUENT_DECLINE"}],
            ),
        ],
    )
    assets = [
        VisualAsset(id="old", scene_id="scene-001", role="primary_visual", image_path=Path("/old.png"), extraction_method="test", source_area_ratio=0.3),
        VisualAsset(id="new", scene_id="scene-002", role="primary_visual", image_path=Path("/new.png"), extraction_method="test", source_area_ratio=0.3),
        VisualAsset(id="target", scene_id="scene-002", role="support_visual_1", image_path=Path("/target.png"), extraction_method="test", source_area_ratio=0.15),
    ]
    composition = [
        CompositionBeat(beat_id=first.id, items=[LayoutItem(asset_id="old", x=0.24, y=0.50, width=0.30, height=0.40)]),
        CompositionBeat(beat_id=second.id, items=[
            LayoutItem(asset_id="new", x=0.65, y=0.50, width=0.30, height=0.40),
            LayoutItem(asset_id="target", x=0.82, y=0.50, width=0.20, height=0.30),
        ]),
    ]
    choreography = ChoreographyDirector().plan(package, [first, second], assets)
    cue = [
        c for c in MotionPlanner().plan([first, second], composition, choreography)
        if c.beat_id == second.id and c.asset_id == "new"
    ][0]
    program = cue.params["program"]

    assert program["name"] == "handoff_then_reject_attempt_recoil"
    settle = program["settle_progress"]
    tail = [frame for frame in program["keyframes"] if frame["progress"] > settle]
    assert tail
    assert max(frame["scale"] for frame in tail) >= 1.05
    assert max(abs(frame["dx"]) + abs(frame["dy"]) for frame in tail) > 0.02

def test_pass2_family_secondary_uses_footprint_locked_reveal() -> None:
    from pathlib import Path
    from app.models import VisualAsset

    beat = _beat()
    family = VisualAsset(
        id="family:secondary-01",
        scene_id=beat.scene_id,
        role="secondary_object",
        image_path=Path("/tmp/family.png"),
        extraction_method="component_mask+pass2_secondary",
        parent_asset_id="family",
        asset_family_id="family",
        render_as_family_canvas=True,
    )
    composition = [CompositionBeat(
        beat_id=beat.id,
        items=[LayoutItem(asset_id=family.id, x=0.5, y=0.5, width=0.5, height=0.5)],
    )]

    cue = MotionPlanner().plan([beat], composition, assets=[family])[0]

    assert cue.params["program"]["name"] == "family_secondary_footprint_locked_reveal"
    assert cue.params["render_constraints"] == {
        "geometry_lock": "authored_footprint",
        "reveal_mode": "alpha_only",
    }
    for frame in cue.params["program"]["keyframes"]:
        assert frame["dx"] == 0.0
        assert frame["dy"] == 0.0
        assert frame["scale"] == 1.0
