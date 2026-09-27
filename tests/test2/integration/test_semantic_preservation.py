from app.render.planner import RenderPlanner


def test_cross_layer_accountability_is_checked_by_render_plan_boundary() -> None:
    assert callable(RenderPlanner._require_executable)
