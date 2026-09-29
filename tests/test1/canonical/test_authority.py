from app.canonical import AUTHORITY_MATRIX, CanonicalAuthority


def test_semantic_authority_is_centralized_and_deterministic() -> None:
    expected = CanonicalAuthority.UNIFIED_FINAL_PACKAGE
    assert AUTHORITY_MATRIX["script"] is expected
    assert AUTHORITY_MATRIX["scene_order"] is expected
    assert AUTHORITY_MATRIX["scene_image"] is expected
    assert AUTHORITY_MATRIX["semantic_asset"] is expected
    assert AUTHORITY_MATRIX["semantic_event"] is expected
    assert AUTHORITY_MATRIX["semantic_relation"] is expected
    assert AUTHORITY_MATRIX["visual_locator"] is expected
