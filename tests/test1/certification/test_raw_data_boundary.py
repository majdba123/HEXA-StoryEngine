from __future__ import annotations

import ast
from pathlib import Path


_RAW_FIELDS = {"manifest", "scene_plan", "semantic_bindings"}
_ALLOWED_RAW_OWNERS = {"final_package", "canonical"}


def _app_root() -> Path:
    return Path(__file__).resolve().parents[3] / "app"


def raw_boundary_violations() -> list[str]:
    """Return raw Final Package knowledge outside the explicit owner allowlist."""

    violations: list[str] = []
    root = _app_root()
    for path in root.rglob("*.py"):
        rel = path.relative_to(root)
        owner = rel.parts[0] if len(rel.parts) > 1 else None
        if owner in _ALLOWED_RAW_OWNERS:
            continue

        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(rel))
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                module = getattr(node, "module", None) or ""
                names = [alias.name for alias in node.names]
                if "RawFinalPackage" in names:
                    violations.append(
                        f"{rel}:{getattr(node, 'lineno', 0)}:RawFinalPackage import"
                    )
                if module.endswith("final_package.models") and "RawFinalPackage" in names:
                    violations.append(
                        f"{rel}:{getattr(node, 'lineno', 0)}:raw model import"
                    )
            elif isinstance(node, ast.Attribute) and node.attr in _RAW_FIELDS:
                violations.append(f"{rel}:{node.lineno}:attribute {node.attr}")
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "getattr"
                and len(node.args) >= 2
                and isinstance(node.args[1], ast.Constant)
                and node.args[1].value in _RAW_FIELDS
            ):
                violations.append(f"{rel}:{node.lineno}:getattr {node.args[1].value}")
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


def test_raw_final_package_knowledge_is_globally_confined_to_boundary() -> None:
    assert raw_boundary_violations() == []


def test_generic_contract_bucket_is_removed() -> None:
    assert contract_bucket_violations() == []
