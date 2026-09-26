from __future__ import annotations

import ast
from pathlib import Path


_RAW_FIELDS = {"manifest", "scene_plan", "semantic_bindings"}
_ALLOWED_RAW_OWNERS = {"final_package", "canonical", "input"}
_FORBIDDEN_DOWNSTREAM = {
    "story", "choreography", "composition", "motion", "text", "vision",
    "director", "render", "cutout",
}


def _app_root() -> Path:
    return Path(__file__).resolve().parents[3] / "app"


def test_raw_final_package_knowledge_is_confined_to_boundary() -> None:
    violations: list[str] = []
    root = _app_root()

    for path in root.rglob("*.py"):
        rel = path.relative_to(root)
        if not rel.parts or rel.parts[0] not in _FORBIDDEN_DOWNSTREAM:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(rel))
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                module = getattr(node, "module", None) or ""
                names = [alias.name for alias in node.names]
                if "RawFinalPackage" in names or module.endswith("final_package.models") and "RawFinalPackage" in names:
                    violations.append(f"{rel}:{getattr(node, 'lineno', 0)}:RawFinalPackage import")
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

    assert violations == []


def test_generic_contract_bucket_is_removed() -> None:
    root = _app_root()
    assert not (root / "contracts").exists()

    violations: list[str] = []
    for path in root.rglob("*.py"):
        rel = path.relative_to(root)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(rel))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("app.contracts"):
                violations.append(f"{rel}:{node.lineno}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("app.contracts"):
                        violations.append(f"{rel}:{node.lineno}")
    assert violations == []
