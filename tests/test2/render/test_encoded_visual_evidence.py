from app.render.evidence import RenderedVisualEvidence


def test_visual_sampling_is_render_evidence() -> None:
    assert RenderedVisualEvidence.__module__ == "app.render.evidence"
