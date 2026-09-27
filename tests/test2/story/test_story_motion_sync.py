from app.motion.planner import MotionPlanner
from app.motion.story_sync_contract import StoryMotionContract


def test_story_motion_sync_is_an_owned_motion_boundary() -> None:
    assert isinstance(MotionPlanner().story_contract, StoryMotionContract)
