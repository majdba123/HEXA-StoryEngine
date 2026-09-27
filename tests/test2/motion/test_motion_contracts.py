from app.motion.interaction_contract import MotionInteractionContract
from app.motion.planner import MotionPlanner


def test_motion_owner_exposes_contract_before_output_leaves_layer() -> None:
    assert isinstance(MotionPlanner().interaction_contract, MotionInteractionContract)
