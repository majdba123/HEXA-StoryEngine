from app.motion.planner import MotionPlanner
from app.motion.rhythm_contract import MotionRhythmContract


def test_rhythm_is_owned_by_motion_planner() -> None:
    assert isinstance(MotionPlanner().rhythm_contract, MotionRhythmContract)
