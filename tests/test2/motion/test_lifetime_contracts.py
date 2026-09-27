from app.motion.lifetime_contract import MotionLifetimeContract
from app.motion.planner import MotionPlanner


def test_lifetime_is_owned_by_motion_planner() -> None:
    assert isinstance(MotionPlanner().lifetime_contract, MotionLifetimeContract)
