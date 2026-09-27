from app.render.transition import VisualTransitionPolicy


def test_render_transition_contract_is_render_owned() -> None:
    assert VisualTransitionPolicy.__module__ == "app.render.transition"
