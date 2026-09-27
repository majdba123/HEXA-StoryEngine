from app.motion import MotionPlanner


def test_motion_interaction_has_no_post_build_runtime_validator() -> None:
    assert not hasattr(MotionPlanner(), "interaction_contract")
