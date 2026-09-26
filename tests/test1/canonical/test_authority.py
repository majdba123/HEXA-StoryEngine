from app.canonical import AUTHORITY_MATRIX, CanonicalAuthority
from app.canonical.authority import (
    resolve_semantic_collection,
    resolve_semantic_mapping,
    resolve_semantic_record,
)


def test_semantic_authority_is_centralized_and_deterministic() -> None:
    assert AUTHORITY_MATRIX["semantic_asset"] is CanonicalAuthority.SEMANTIC_BINDINGS
    assert AUTHORITY_MATRIX["semantic_event"] is CanonicalAuthority.SEMANTIC_BINDINGS
    assert AUTHORITY_MATRIX["semantic_relation"] is CanonicalAuthority.SEMANTIC_BINDINGS
    assert resolve_semantic_record(
        {"role": "structural", "only_plan": 1},
        {"role": "semantic", "only_binding": 2},
    ) == {"role": "semantic", "only_plan": 1, "only_binding": 2}
    assert resolve_semantic_collection(["plan"], ["binding"]) == ["binding"]
    assert resolve_semantic_collection(["plan"], None) == ["plan"]
    assert resolve_semantic_mapping({"type": "plan"}, {"type": "binding"}) == {
        "type": "binding"
    }
