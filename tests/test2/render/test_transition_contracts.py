from app.render.transition_contract import RenderTransitionContract


def test_render_transition_contract_is_render_owned() -> None:
    assert RenderTransitionContract.__module__ == "app.render.transition_contract"
