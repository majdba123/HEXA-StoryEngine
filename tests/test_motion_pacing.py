from app.models import CompositionBeat, LayoutItem, StoryBeat
from app.motion.planner import MotionPlanner


def _beat(duration: float, item_count: int) -> tuple[StoryBeat, CompositionBeat]:
    beat = StoryBeat(
        id="beat-001",
        scene_id="scene-001",
        start=1.0,
        end=1.0 + duration,
        narration="spoken phrase",
        primary_asset_ids=["a0"],
        support_asset_ids=[f"a{i}" for i in range(1, item_count)],
        action="INTRODUCE",
    )
    composition = CompositionBeat(
        beat_id=beat.id,
        items=[LayoutItem(asset_id=f"a{i}", x=0.2 + i * 0.05, y=0.5, width=0.2, height=0.3) for i in range(item_count)],
    )
    return beat, composition


def test_long_beat_protects_readable_hold_and_slow_entrances() -> None:
    beat, composition = _beat(2.8, 5)
    cues = MotionPlanner().plan([beat], [composition])
    strong = [cue for cue in cues if cue.kind != "context_in"]
    assert strong
    assert all(cue.end - cue.start >= 0.34 for cue in strong)
    assert beat.end - max(cue.end for cue in strong) >= 0.28
    starts = [cue.start for cue in strong]
    assert all((b - a) >= 0.27 for a, b in zip(starts, starts[1:]))


def test_short_beat_does_not_machine_gun_many_objects() -> None:
    beat, composition = _beat(0.95, 7)
    cues = MotionPlanner().plan([beat], [composition])
    strong = [cue for cue in cues if cue.kind != "context_in"]
    context = [cue for cue in cues if cue.kind == "context_in"]
    assert len(strong) <= 2
    assert context
    assert len(strong) + len(context) == 7


def test_quiet_context_overlap_is_not_treated_as_multi_element_pop(tmp_path) -> None:
    from app.models import RenderPlan, VisualAsset
    from app.recovery.detector import RecoveryDetector

    beat, composition = _beat(0.95, 7)
    cues = MotionPlanner().plan([beat], [composition])
    assets = []
    for index in range(7):
        path = tmp_path / f"a{index}.png"
        path.write_bytes(b"asset")
        assets.append(VisualAsset(
            id=f"a{index}",
            scene_id="scene-001",
            role="object",
            image_path=path,
            extraction_method="test",
        ))
    plan = RenderPlan(
        duration=2.0,
        story=[beat],
        composition=[composition],
        motion=cues,
        assets=assets,
    )
    codes = {issue.code for issue in RecoveryDetector().inspect_plan(plan)}
    assert "MULTI_ELEMENT_POP" not in codes
