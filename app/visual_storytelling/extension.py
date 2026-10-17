"""Strict sidecar validation and conservative RESULT_FOCUS execution.

The initial contract only authors RESULT_FOCUS. It never manufactures missing
events, new assets, narration timing, or animation. A directive can strengthen
an *already certified* backdrop-focus treatment and otherwise abstains with
machine-readable reasons. Production V1 remains opt-in.
"""
from __future__ import annotations

import json
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.models import RenderPlan
from app.shared.errors import InvalidPackageError

SIDECAR_NAME = "visual_storytelling_v1.json"
CONTRACT = "HEXA_VISUAL_STORYTELLING_SIDECAR"
VERSION = "1.0"
MAX_SIDECAR_BYTES = 1_048_576
MAX_MANIFEST_BYTES = 16_777_216


@dataclass(frozen=True, slots=True)
class ResultFocusDirective:
    directive_id: str
    scene_id: str
    event_id: str
    leader_asset_id: str
    target_asset_id: str


@dataclass(frozen=True, slots=True)
class VisualSidecar:
    package_id: str
    directives: tuple[ResultFocusDirective, ...]


def _fail(message: str) -> None:
    raise InvalidPackageError("VISUAL_STORYTELLING_V1_INVALID: " + message)


def _json_object(data: bytes, name: str) -> dict[str, Any]:
    def no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                _fail(f"duplicate JSON key in {name}: {key}")
            result[key] = value
        return result

    try:
        payload = json.loads(data.decode("utf-8-sig"), object_pairs_hook=no_duplicates)
    except (UnicodeError, json.JSONDecodeError) as exc:
        _fail(f"invalid JSON in {name}: {exc}")
    if not isinstance(payload, dict):
        _fail(f"{name} must be a JSON object")
    return payload


def _read_pair(source: Path) -> tuple[bytes, bytes] | None:
    source = source.expanduser().resolve()
    if source.is_dir():
        manifest = source / "package.json"
        sidecar = source / SIDECAR_NAME
        if not sidecar.is_file():
            return None
        if not manifest.is_file() or sidecar.is_symlink() or manifest.is_symlink():
            _fail("unsafe or missing package.json / sidecar")
        if sidecar.stat().st_size > MAX_SIDECAR_BYTES or manifest.stat().st_size > MAX_MANIFEST_BYTES:
            _fail("JSON exceeds allowed size")
        return manifest.read_bytes(), sidecar.read_bytes()
    if source.suffix.lower() != ".zip":
        _fail("source must be a .zip or package directory")
    try:
        with zipfile.ZipFile(source) as archive:
            # The existing loader permits one wrapping directory; mirror this without
            # interpreting arbitrary nested paths or following ZIP member links.
            names = [info.filename for info in archive.infolist() if not info.is_dir()]
            matches = [name for name in names if name == SIDECAR_NAME or name.endswith("/" + SIDECAR_NAME)]
            if not matches:
                return None
            if len(matches) != 1:
                _fail("duplicate sidecar ZIP entries")
            sidecar_name = matches[0]
            prefix = sidecar_name[: -len(SIDECAR_NAME)]
            if prefix and ("/" in prefix.strip("/")):
                _fail("sidecar must be at the package root")
            manifest_name = prefix + "package.json"
            if names.count(manifest_name) != 1:
                _fail("missing or duplicated package.json")
            sidecar_info = archive.getinfo(sidecar_name)
            manifest_info = archive.getinfo(manifest_name)
            if sidecar_info.file_size > MAX_SIDECAR_BYTES or manifest_info.file_size > MAX_MANIFEST_BYTES:
                _fail("JSON exceeds allowed size")
            return archive.read(manifest_name), archive.read(sidecar_name)
    except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
        _fail(f"cannot read package ZIP: {exc}")
    return None


def _exact_keys(value: dict, expected: set[str], context: str) -> None:
    if set(value) != expected:
        _fail(f"{context}: wrong keys: missing={sorted(expected - set(value))}, extra={sorted(set(value) - expected)}")


def _non_empty(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 256:
        _fail(f"{context}: expected nonempty string up to 256 characters")
    return value


def load_sidecar(source: Path) -> VisualSidecar | None:
    """Read an optional addendum without changing, repairing or unpacking its source."""
    pair = _read_pair(source)
    if pair is None:
        return None
    original = _json_object(pair[0], "package.json")
    sidecar = _json_object(pair[1], SIDECAR_NAME)
    _exact_keys(sidecar, {"contract", "version", "package_id", "scenes"}, SIDECAR_NAME)
    if sidecar["contract"] != CONTRACT or sidecar["version"] != VERSION:
        _fail("unsupported sidecar contract or version")
    package_id = _non_empty(sidecar["package_id"], "package_id")
    if original.get("package_id") != package_id:
        _fail("package_id does not match package.json")
    if not isinstance(original.get("scenes"), list) or not isinstance(sidecar["scenes"], list):
        _fail("scenes must be arrays")
    originals: dict[str, dict] = {}
    for scene in original["scenes"]:
        if not isinstance(scene, dict):
            _fail("malformed original scene")
        scene_id = scene.get("scene_id")
        if not isinstance(scene_id, str) or scene_id in originals:
            _fail("missing or duplicate original scene ID")
        originals[scene_id] = scene
    directives: list[ResultFocusDirective] = []
    seen_scenes: set[str] = set()
    seen_ids: set[str] = set()
    for entry in sidecar["scenes"]:
        if not isinstance(entry, dict):
            _fail("sidecar scene entry must be object")
        _exact_keys(entry, {"scene_id", "directives"}, "sidecar scene")
        scene_id = _non_empty(entry["scene_id"], "scene_id")
        if scene_id not in originals or scene_id in seen_scenes:
            _fail(f"unknown or duplicate scene: {scene_id}")
        seen_scenes.add(scene_id)
        if not isinstance(entry["directives"], list) or not entry["directives"]:
            _fail(f"empty or invalid directive list: {scene_id}")
        scene = originals[scene_id]
        events = {e.get("semantic_event_id"): e for e in scene.get("semantic_events", [])
                  if isinstance(e, dict)}
        objects = {o.get("asset_id") for o in scene.get("objects", [])
                   if isinstance(o, dict)}
        for raw in entry["directives"]:
            if not isinstance(raw, dict):
                _fail(f"directive must be object in {scene_id}")
            _exact_keys(raw, {"directive_id", "semantic_event_id", "action",
                              "leader_asset_id", "target_asset_id", "evidence", "priority"},
                        f"directive in {scene_id}")
            directive_id = _non_empty(raw["directive_id"], "directive_id")
            event_id = _non_empty(raw["semantic_event_id"], "semantic_event_id")
            leader = _non_empty(raw["leader_asset_id"], "leader_asset_id")
            target = _non_empty(raw["target_asset_id"], "target_asset_id")
            if directive_id in seen_ids:
                _fail(f"duplicate directive_id: {directive_id}")
            seen_ids.add(directive_id)
            if raw["action"] != "RESULT_FOCUS" or raw["evidence"] != "EVENT_RESULT" or raw["priority"] != "NORMAL":
                _fail(f"unsupported action, evidence or priority: {directive_id}")
            event = events.get(event_id)
            if event is None or leader not in objects or target not in objects or leader == target:
                _fail(f"invalid event or object reference: {directive_id}")
            if event.get("visual_leader_asset_id") != leader or target not in event.get("result_asset_ids", []):
                _fail(f"RESULT_FOCUS must name its event's leader and authored result: {directive_id}")
            directives.append(ResultFocusDirective(directive_id, scene_id, event_id, leader, target))
    if not directives:
        _fail("sidecar contains no directives")
    return VisualSidecar(package_id, tuple(directives))


def enhance_reference_plan(source: Path, plan: RenderPlan, workspace: Path) -> RenderPlan:
    """Opt-in post-plan refinement; write decisions and keep source ZIP untouched.

    The only currently permitted visual change is a bounded additional contrast
    boost to an already authorized focus wash. Missing eligibility abstains.
    """
    sidecar = load_sidecar(source)
    diagnostics: dict[str, Any] = {
        "version": VERSION,
        "status": "ABSENT" if sidecar is None else "EVALUATED",
        "package_id": sidecar.package_id if sidecar else None,
        "applied": 0,
        "abstained": 0,
        "directives": [],
    }
    output = plan
    if sidecar is not None:
        index = {(beat.scene_id, beat.id): beat for beat in plan.story}
        motion = list(plan.motion)
        for directive in sidecar.directives:
            outcome = {"directive_id": directive.directive_id, "scene_id": directive.scene_id,
                       "event_id": directive.event_id, "action": "RESULT_FOCUS"}
            selected: tuple[int, dict] | None = None
            for i, cue in enumerate(motion):
                beat = index.get((directive.scene_id, cue.beat_id))
                if beat is None or not any(
                    event.event_id == directive.event_id and event.result_asset_ids
                    and event.leader_asset_ids
                    for event in beat.event_authorities
                ):
                    continue
                wash = cue.params.get("focus_wash")
                if (isinstance(wash, dict) and wash.get("event_id") == directive.event_id
                        and wash.get("style") == "reference_wash"
                        and wash.get("focus_asset_ids")
                        and 0.0 <= float(wash.get("tint_alpha", -1)) <= 0.42):
                    selected = (i, wash)
                    break
            if selected is None:
                outcome["status"] = "ABSTAINED"
                outcome["reason"] = "no_preverified_wash_for_authored_result"
                diagnostics["abstained"] += 1
            else:
                offset, wash = selected
                old = motion[offset]
                # No change to timing, focus ownership, compositing order, text or geometry.
                enhanced_wash = {**wash, "tint_alpha": round(min(0.48, float(wash["tint_alpha"]) + 0.04), 4)}
                motion[offset] = old.model_copy(update={"params": {
                    **old.params, "focus_wash": enhanced_wash,
                    "visual_storytelling_v1": directive.directive_id,
                }})
                outcome["status"] = "APPLIED"
                outcome["reason"] = "increased_existing_certified_focus_contrast"
                diagnostics["applied"] += 1
            diagnostics["directives"].append(outcome)
        output = plan.model_copy(update={"motion": motion})
    diagnostics_dir = workspace / "diagnostics"
    diagnostics_dir.mkdir(parents=True, exist_ok=True)
    (diagnostics_dir / "visual-storytelling-v1.json").write_text(
        json.dumps(diagnostics, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    if output is not plan:
        (workspace / "render-plan.json").write_text(
            json.dumps(output.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return output
