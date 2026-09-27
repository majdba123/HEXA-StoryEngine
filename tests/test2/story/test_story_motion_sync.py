from app.motion import MotionPlanner


def test_story_motion_sync_has_no_post_build_runtime_validator() -> None:
    assert not hasattr(MotionPlanner(), "story_contract")
