from app.motion.continuity import ContinuityContract
from app.motion.planner import MotionPlanner


def test_asset_lifecycle_is_owned_by_motion() -> None:
    assert isinstance(MotionPlanner().continuity_contract, ContinuityContract)
