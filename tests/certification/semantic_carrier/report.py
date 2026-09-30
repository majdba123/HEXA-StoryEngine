"""Write the Semantic Carrier Resolver certification summary.

    python -m tests.certification.semantic_carrier.report [--extra real-corpus.json]

Runs the acceptance suite, derives every count from the suite's own constants (so the
summary cannot drift from what actually ran) and measures resolver scaling. ``--extra``
merges externally gathered evidence: six-package confidence distribution, baseline
comparison, Level A-E and CI results.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ElementTree
from pathlib import Path

from app.story.carrier_resolver import SemanticCarrierResolver
from tests.support.carrier_scene import Cutout, SceneSpec, Unit, build_package, locator_for

from . import cases
from . import test_assignment_certification as assignment
from . import test_generated_acceptance as generated
from . import test_resolver_acceptance as resolver

OUTPUT = Path(__file__).resolve().parents[3] / "docs" / "certification"
SUITE = Path(__file__).resolve().parent


def _performance() -> dict[str, dict[str, float]]:
    samples = {}
    for count in resolver.PERFORMANCE_SIZES:
        columns = max(1, int(count ** 0.5 + 0.999))
        cell = 1000 // columns
        boxes = [((i % columns) * cell + 5, (i // columns) * cell + 5, cell - 10, cell - 10)
                 for i in range(count)]
        built = build_package([SceneSpec(
            resolver.PHRASE,
            tuple(Unit(f"U{i:03d}", (0, 0), locator=locator_for(b)) for i, b in enumerate(boxes)),
            tuple(Cutout(f"asset-{i + 1:03d}", b) for i, b in enumerate(boxes)), (),
        )])
        scene = built.package.scenes[0]
        SemanticCarrierResolver().resolve(scene=scene, assets=built.assets)
        runs = []
        for _ in range(3):
            started = time.perf_counter()
            SemanticCarrierResolver().resolve(scene=scene, assets=built.assets)
            runs.append((time.perf_counter() - started) * 1000)
        samples[str(count)] = {"wall_ms_median": round(sorted(runs)[1], 2),
                               "candidate_matrix_cells": count * count}
    return samples


def _run_suite() -> dict[str, int]:
    with tempfile.TemporaryDirectory() as folder:
        report = Path(folder) / "suite.xml"
        subprocess.run(
            [sys.executable, "-m", "pytest", str(SUITE), "-q", "-p", "no:cacheprovider",
             "-W", "ignore::DeprecationWarning", f"--junitxml={report}"],
            check=False,
        )
        root = ElementTree.parse(report).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    return {key: sum(int(s.get(key, 0)) for s in suites)
            for key in ("tests", "failures", "errors", "skipped")}


def build(extra: dict | None = None) -> dict:
    must_fail = sum(1 for m, _ in generated.MUTATED if m in generated.MUTATION_MUST_FAIL)
    role_failures = len(resolver.ROLES) * 3  # missing, ambiguous, hidden
    summary = {
        "suite": "tests/certification/semantic_carrier",
        "pytest": _run_suite(),
        "assignment": {
            "generated_matrices": assignment.ASSIGNMENT_CASES,
            "shapes": [f"{r}x{c}" for r, c in assignment.SHAPES],
            "patterns": list(assignment.PATTERNS),
            "exact_optimum_comparisons": assignment.ASSIGNMENT_CASES,
            "optimum_method": "bitmask dynamic programme (exhaustive, all shapes up to 10x10)",
            "boundary_deltas": list(assignment.BOUNDARY_DELTAS),
        },
        "generated_cases": {
            "seed_range": "per family: clean 0-20, complex 0-16, failure 0-24, mutation 0-14",
            "total": len(generated.POSITIVE) + len(generated.FAILURES) + len(generated.MUTATED),
            "clean_positive": len(generated.CLEAN),
            "complex_positive": len(generated.COMPLEX),
            "expected_failure": len(generated.FAILURES),
            "mutation": len(generated.MUTATED),
            "through_story": len(generated.POSITIVE) + len(generated.FAILURES) + len(generated.MUTATED),
            "through_render_plan": len(generated.RENDER_PLAN),
            "families": {
                "clean": list(cases.CLEAN_FAMILIES), "complex": list(cases.COMPLEX_FAMILIES),
                "failure": cases.FAILURE_FAMILIES, "mutations": list(cases.MUTATIONS),
            },
        },
        "expected_failures_total": len(generated.FAILURES) + must_fail + role_failures + 2,
        "determinism": {
            "assignment_permutation_comparisons": assignment.PERMUTATION_COMPARISONS,
            "resolver_shuffled_input_comparisons": len(generated.POSITIVE),
            "repeated_executions": len(generated.REPRODUCIBILITY) * generated.REPRODUCIBILITY_RUNS,
        },
        "role_matrix": {"roles": list(resolver.ROLES), "situations": list(resolver.SITUATIONS)},
        "performance": _performance(),
    }
    summary.update(extra or {})
    return summary


def markdown(summary: dict) -> str:
    run, gen, det = summary["pytest"], summary["generated_cases"], summary["determinism"]
    lines = [
        "# Semantic Carrier Resolver — acceptance certification",
        "",
        f"- Suite: `{summary['suite']}` — {run['tests']} tests, {run['failures']} failures, "
        f"{run['errors']} errors, {run['skipped']} skipped",
        f"- Assignment matrices: {summary['assignment']['generated_matrices']} "
        f"(all compared with an exact optimum)",
        f"- Generated cases: {gen['total']} = {gen['clean_positive']} clean + "
        f"{gen['complex_positive']} complex + {gen['expected_failure']} expected-failure + "
        f"{gen['mutation']} mutation; {gen['through_render_plan']} through RenderPlan",
        f"- Expected typed failures exercised: {summary['expected_failures_total']}",
        f"- Determinism: {det['assignment_permutation_comparisons']} assignment permutations, "
        f"{det['resolver_shuffled_input_comparisons']} shuffled resolutions, "
        f"{det['repeated_executions']} repeated executions",
        "",
        "## Resolver scaling (one scene)",
        "",
        "| intents | candidate cells | wall ms (median of 3) |",
        "|---:|---:|---:|",
    ]
    lines += [f"| {count} | {row['candidate_matrix_cells']} | {row['wall_ms_median']} |"
              for count, row in summary["performance"].items()]
    for title, key in (("Real packages", "real_packages"), ("Findings", "findings"),
                       ("Known risks", "known_risks"), ("Verdict", "verdict")):
        if key in summary:
            lines += ["", f"## {title}", "", "```json",
                      json.dumps(summary[key], ensure_ascii=False, indent=1), "```"]
    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    extra = None
    if len(argv) == 2 and argv[0] == "--extra":
        extra = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
    summary = build(extra)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "semantic-carrier-certification-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUTPUT / "semantic-carrier-certification-report.md").write_text(
        markdown(summary), encoding="utf-8")
    print(json.dumps(summary["pytest"]), "->", OUTPUT)
    return 1 if summary["pytest"]["failures"] or summary["pytest"]["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
