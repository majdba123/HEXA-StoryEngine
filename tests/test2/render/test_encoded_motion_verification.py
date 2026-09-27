from app.render.verification import EncodedMotionVerifier


def test_encoded_motion_is_proof_only_and_render_owned() -> None:
    assert EncodedMotionVerifier.__module__ == "app.render.verification"
