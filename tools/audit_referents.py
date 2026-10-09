"""Audit authored cross-scene referent identity in Final Package 2.0 packages.

    python tools/audit_referents.py PACKAGE [PACKAGE ...]   # directory or .zip

Reports only what the package authors (``referent_id``); it never infers a referent from
names, roles, source_asset_id, unit_id, images or scene order. Packages are loaded through
the production FinalPackageLoader, so invalid referent ids or ambiguous same-scene
carriers fail exactly as they do in production. Output is deterministic JSON.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.final_package import FinalPackageLoader  # noqa: E402
from app.shared.errors import HexaError  # noqa: E402


def audit(package_path: Path) -> dict:
    with tempfile.TemporaryDirectory(prefix="hexa-referents-") as workspace:
        try:
            package = FinalPackageLoader().load(package_path, Path(workspace))
        except HexaError as exc:
            return {"package": package_path.name, "valid": False, "error": str(exc)}
    scenes = sorted(package.scenes, key=lambda scene: scene.order)
    order = {scene.id: index for index, scene in enumerate(scenes)}
    carriers: dict[str, dict[str, list[str]]] = {}
    objects = authored = 0
    for scene in scenes:
        for unit in scene.units:
            objects += 1
            if unit.referent_id is None:
                continue
            authored += 1
            carriers.setdefault(unit.referent_id, {}).setdefault(scene.id, []).append(unit.asset_id)
    adjacent, recurrences = [], []
    for referent_id in sorted(carriers):
        scene_ids = sorted(carriers[referent_id], key=order.__getitem__)
        for previous, current in zip(scene_ids, scene_ids[1:]):
            row = {"referent_id": referent_id, "from_scene": previous, "to_scene": current,
                   "from_assets": sorted(carriers[referent_id][previous]),
                   "to_assets": sorted(carriers[referent_id][current])}
            (adjacent if order[current] - order[previous] == 1 else recurrences).append(row)
    return {
        "package": package_path.name,
        "valid": True,
        "package_id": package.package_id,
        "scenes": len(scenes),
        "objects": objects,
        "objects_with_referent_id": authored,
        "unique_referents": len(carriers),
        "referents_spanning_multiple_scenes": sorted(r for r, s in carriers.items() if len(s) > 1),
        "adjacent_scene_candidates": adjacent,
        "non_adjacent_recurrences": recurrences,
        "same_scene_compound_carriers": [
            {"referent_id": r, "scene": s, "assets": sorted(carriers[r][s])}
            for r in sorted(carriers) for s in sorted(carriers[r], key=order.__getitem__)
            if len(carriers[r][s]) > 1
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("packages", nargs="+", type=Path)
    args = parser.parse_args()
    reports = [audit(path) for path in args.packages]
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(reports, ensure_ascii=False, indent=1))
    return 0 if all(report["valid"] for report in reports) else 1


if __name__ == "__main__":
    sys.exit(main())
