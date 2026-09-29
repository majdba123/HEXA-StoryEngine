from __future__ import annotations

import ast
from pathlib import Path


_LEGACY_RUNTIME_FIELDS = {
    "manifest",
    "scene_plan",
    "semantic_bindings",
    "manifest_objects",
    "manifest_assets",
    "semantic_binding_schema_name",
    "semantic_binding_schema_version",
    "semantic_bindings_present",
}
_LEGACY_TYPES = {"RawFinalPackage", "CanonicalNormalizer", "PackageModel"}


def _app_root() -> Path:
    return Path(__file__).resolve().parents[3] / "app"


def legacy_contract_violations() -> list[str]:
    """Return any production dependency on the retired 1.x file-shaped contract."""

    violations: list[str] = []
    root = _app_root()
    for path in root.rglob("*.py"):
        rel = path.relative_to(root)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(rel))
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = {alias.name for alias in node.names}
                retired = names & _LEGACY_TYPES
                for name in sorted(retired):
                    violations.append(f"{rel}:{getattr(node, 'lineno', 0)}:{name} import")
            elif isinstance(node, ast.Attribute) and node.attr in _LEGACY_RUNTIME_FIELDS:
                violations.append(f"{rel}:{node.lineno}:attribute {node.attr}")
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "getattr"
                and len(node.args) >= 2
                and isinstance(node.args[1], ast.Constant)
                and node.args[1].value in _LEGACY_RUNTIME_FIELDS
            ):
                violations.append(f"{rel}:{node.lineno}:getattr {node.args[1].value}")
    if (root / "canonical" / "normalizer.py").exists():
        violations.append("canonical/normalizer.py still exists")
    return violations


def contract_bucket_violations() -> list[str]:
    root = _app_root()
    violations: list[str] = []
    if (root / "contracts").exists():
        violations.append("app/contracts still exists")

    for path in root.rglob("*.py"):
        rel = path.relative_to(root)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(rel))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("app.contracts"):
                violations.append(f"{rel}:{node.lineno}:app.contracts import")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("app.contracts"):
                        violations.append(f"{rel}:{node.lineno}:app.contracts import")
    return violations


def test_retired_1x_contract_has_no_runtime_surface() -> None:
    assert legacy_contract_violations() == []


def test_generic_contract_bucket_is_removed() -> None:
    assert contract_bucket_violations() == []
