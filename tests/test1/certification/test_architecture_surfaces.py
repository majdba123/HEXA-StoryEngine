from __future__ import annotations

import ast
from pathlib import Path

from app.canonical import CanonicalAsset
from app.canonical.models import CanonicalRecord
from app.layout.footprint import AlphaFootprintResolver


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def test_obsolete_compatibility_surfaces_are_absent() -> None:
    assert not (REPOSITORY_ROOT / "app" / "contracts").exists()
    assert not list((REPOSITORY_ROOT / "app" / "input").glob("*.py"))
    assert not (REPOSITORY_ROOT / "app" / "choreography" / "binding.py").exists()
    assert not (REPOSITORY_ROOT / "app" / "composition" / "footprint.py").exists()


def test_canonical_records_do_not_expose_mapping_compatibility() -> None:
    for name in ("get", "items", "keys", "values", "__getitem__"):
        assert not hasattr(CanonicalRecord, name)
        assert not hasattr(CanonicalAsset, name)


def test_text_director_uses_layout_footprint_owner() -> None:
    source = (REPOSITORY_ROOT / "app" / "composition" / "text_director.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    imports = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }
    assert "app.layout.footprint" in imports
    assert "app.composition.footprint" not in imports
    assert AlphaFootprintResolver.__module__ == "app.layout.footprint"


def test_refinement_consumer_has_no_canonical_mapping_access() -> None:
    source = (REPOSITORY_ROOT / "app" / "pipeline.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    refinement = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "_apply_refinement"
    )
    calls = [
        node
        for node in ast.walk(refinement)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    ]
    assert not any(
        isinstance(call.func.value, ast.Name)
        and call.func.value.id == "unit"
        and call.func.attr in {"get", "items", "keys", "values"}
        for call in calls
    )


def test_recovery_architecture_cannot_be_reintroduced() -> None:
    app_root = REPOSITORY_ROOT / "app"
    assert not (app_root / "recovery").exists()

    forbidden = {
        "app.recovery",
        "Stage.recovery",
        "RecoveryManager",
        "RecoveryDetector",
        "RecoveryCandidateEvaluator",
        "RecoveryRegistry",
        "RecoveryHistory",
        "recovery-history.jsonl",
        "known-issues.json",
        "recovered-video-",
        "recovered-final-",
        "strict_boundary_coverage",
        "repair_motion_readability",
        "semantic_authority_change_allowed",
        "RecoveryStatus",
        "KnownIssue",
        "invalidate_from_stage",
        "record_outcome",
        "retry_cutout",
        "rebuild_story_timing",
        "rebuild_composition",
        "rebuild_motion",
        "repair_text_layout",
        "rerender_strict_handoff",
        "remux_audio",
    }
    sources = {
        path.relative_to(REPOSITORY_ROOT): path.read_text(encoding="utf-8")
        for path in app_root.rglob("*.py")
    }
    violations = {
        str(path): sorted(token for token in forbidden if token in source)
        for path, source in sources.items()
        if any(token in source for token in forbidden)
    }
    assert not violations

    pipeline_tree = ast.parse(sources[Path("app/pipeline.py")])
    pipeline_methods = {
        node.name
        for node in ast.walk(pipeline_tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert not {name for name in pipeline_methods if name.startswith("_recover_")}

    obsolete_terminology = {
        str(path): "recovery"
        for path, source in sources.items()
        if "recovery" in source.lower()
    }
    assert not obsolete_terminology
