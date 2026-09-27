from app.motion.lifetime import SemanticVisualLifetimeIndex
from app.motion.planner import MotionPlanner


def test_lifetime_is_owned_by_motion_planner() -> None:
    assert not hasattr(MotionPlanner(), "lifetime_contract")
    assert SemanticVisualLifetimeIndex.__module__ == "app.motion.lifetime"
