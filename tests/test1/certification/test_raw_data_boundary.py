from pathlib import Path
import re


def test_raw_final_package_json_does_not_leak_to_production_layers() -> None:
    root = Path(__file__).resolve().parents[3] / "app"
    allowed = {"final_package", "input"}
    forbidden = (
        re.compile(r"package\.semantic_bindings\b"),
        re.compile(r"package\.scene_plan\b"),
        re.compile(r"package\.manifest\b"),
    )
    violations: list[str] = []
    for path in root.rglob("*.py"):
        rel = path.relative_to(root)
        if rel.parts and rel.parts[0] in allowed:
            continue
        text = path.read_text(encoding="utf-8")
        for pattern in forbidden:
            if pattern.search(text):
                violations.append(f"{rel}:{pattern.pattern}")
    assert violations == []
