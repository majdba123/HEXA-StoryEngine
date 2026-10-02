"""Sprint 3.75 holdout reporting and the CI execution gate.

``python -m tests.package_holdouts.report require <junit.xml>`` fails unless exactly the
certified holdout matrix executed with no skip, xfail, failure or error.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def write_report(path: Path, **values: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema_version": 1, **values}, indent=2, sort_keys=True), encoding="utf-8")
    return path


def expected_test_count() -> int:
    from tests.package_holdouts.cases import (
        OPENING_COVERAGE_TESTS,
        encoded_cases,
        full_render_cases,
        structural_cases,
    )

    return (
        len(structural_cases()) + len(encoded_cases()) + len(full_render_cases())
        + OPENING_COVERAGE_TESTS
    )


def require_executed(junit_xml: Path, expected: int) -> list[str]:
    import xml.etree.ElementTree as ElementTree

    root = ElementTree.parse(junit_xml).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    total = sum(int(suite.get("tests", 0)) for suite in suites)
    problems = []
    if total != expected:
        problems.append(f"{total} holdout tests executed, expected exactly {expected}")
    for key in ("skipped", "failures", "errors"):
        count = sum(int(suite.get(key, 0)) for suite in suites)
        if count:
            problems.append(f"{count} {key.upper()}")
    return problems


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[0] != "require":
        print(__doc__)
        return 2
    expected = expected_test_count()
    problems = require_executed(Path(argv[1]), expected)
    for line in problems:
        print(f"SPRINT 3.75 HOLDOUT GATE FAILED: {line}")
    if not problems:
        print(f"Sprint 3.75 holdout gate: {expected}/{expected} executed and passed")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
