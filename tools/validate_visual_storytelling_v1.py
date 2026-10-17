"""Validate a Unified 2.0 package and its optional Visual Storytelling V1 addendum.

Requires the actual StoryEngine repository dependencies, unlike an LLM-only
generation session. This is structural validation, not video/render certification.
"""
from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from app.final_package.loader import FinalPackageLoader
from app.visual_storytelling import load_sidecar


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path, help="Path to Unified Final Package ZIP or directory")
    args = parser.parse_args()
    try:
        with tempfile.TemporaryDirectory(prefix="hexa-vs1-check-") as scratch:
            package = FinalPackageLoader().load(args.package, Path(scratch))
            sidecar = load_sidecar(args.package)
            if sidecar is None:
                raise ValueError("visual_storytelling_v1.json is missing")
            if package.package_id != sidecar.package_id:
                raise ValueError("canonical package ID and sidecar ID differ")
            print(json.dumps({
                "unified_2_0": "PASS",
                "visual_storytelling_v1_structure": "PASS",
                "package_id": package.package_id,
                "scene_count": len(package.scenes),
                "directive_count": len(sidecar.directives),
                "render_certification": "NOT_RUN",
            }, ensure_ascii=False, indent=2))
    except Exception as exc:
        print(json.dumps({"validation": "FAILED", "reason": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
