from app.transcription.service import TranscriptionService, _WORD_RE


def test_script_fallback_anchors_punctuation_to_real_pause() -> None:
    service = TranscriptionService(model_name="small")
    script = "alpha beta. gamma delta."
    tokens = list(_WORD_RE.finditer(script))
    weights = [service._spoken_weight(token.group()) for token in tokens]

    positions = service._allocate_script_over_intervals(
        script,
        tokens,
        weights,
        [(0.0, 1.0), (1.6, 3.0)],
    )

    assert len(positions) == 4
    assert positions[1][1] == 1.0
    assert positions[2][0] == 1.6
    assert all(start < end for start, end in positions)
    assert all(positions[index][1] <= positions[index + 1][0] for index in range(3))
