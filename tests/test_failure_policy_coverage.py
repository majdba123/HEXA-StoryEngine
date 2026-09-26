from __future__ import annotations

import ast
from pathlib import Path

from app.recovery.policy import failure_policy


def _emitted_codes() -> set[str]:
    app_root = Path(__file__).resolve().parents[1] / "app"
    codes: set[str] = set()
    for path in app_root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Dict):
                for key, value in zip(node.keys, node.values):
                    if (
                        isinstance(key, ast.Constant)
                        and key.value == "code"
                        and isinstance(value, ast.Constant)
                        and isinstance(value.value, str)
                    ):
                        codes.add(value.value)
            if isinstance(node, ast.Call):
                for keyword in node.keywords:
                    if (
                        keyword.arg == "code"
                        and isinstance(keyword.value, ast.Constant)
                        and isinstance(keyword.value.value, str)
                    ):
                        codes.add(keyword.value.value)
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
                if not isinstance(node.value.value, str):
                    continue
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "code":
                        codes.add(node.value.value)
            if isinstance(node, ast.AnnAssign) and isinstance(node.value, ast.Constant):
                if (
                    isinstance(node.target, ast.Name)
                    and node.target.id == "code"
                    and isinstance(node.value.value, str)
                ):
                    codes.add(node.value.value)
    return codes


def test_every_production_error_and_violation_code_has_failure_policy() -> None:
    emitted = _emitted_codes()
    missing = sorted(code for code in emitted if failure_policy(code) is None)
    assert missing == []
