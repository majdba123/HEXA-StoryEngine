from app.motion.planner import MotionPlanner
from app.motion.rhythm import ReferenceRhythmPolicy


def test_rhythm_is_owned_by_motion_planner() -> None:
    assert not hasattr(MotionPlanner(), "rhythm_contract")
    assert ReferenceRhythmPolicy.__module__ == "app.motion.rhythm"
