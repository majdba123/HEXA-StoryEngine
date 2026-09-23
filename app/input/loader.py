from __future__ import annotations

import hashlib
import json
import shutil
import zipfile
from pathlib import Path

from app.models import PackageModel, SceneSource
from app.shared.errors import InvalidPackageError

_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
_SEMANTIC_BINDING_SCHEMAS = {"HEXA_SEMANTIC_BINDINGS", "HEXA_ASSET_LEVEL_SEMANTIC_BINDINGS"}
_ASSET_LEVEL_BINDING_TYPES = {"EXPLICIT", "SEMANTIC", "SUPPORT", "PARENT", "AMBIGUOUS"}
_SEMANTIC_GROUP_POLICIES = {"SEQUENTIAL_WITHIN_PHRASE", "SIMULTANEOUS_VISUAL_UNIT"}


class FinalPackageLoader:
    def load(self, source: Path, workspace: Path, script_path: Path | None = None) -> PackageModel:
        source = source.expanduser().resolve()
        if not source.exists():
            raise InvalidPackageError(f"Final Package not found: {source}")
        package_root = self._materialize(source, workspace)
        manifest_path = package_root / "manifest.json"
        manifest = self._load_json(manifest_path) if manifest_path.exists() else {}
        script = self._load_script(package_root, script_path, manifest)
        scene_plan = self._load_scene_plan(package_root, manifest)
        semantic_bindings = self._load_semantic_bindings(package_root, manifest)
        scenes = self._discover_scenes(package_root, manifest, scene_plan)
        if not scenes:
            raise InvalidPackageError("Final Package contains no scene images")
        self._validate_scene_unit_visual_locators(scenes)
        self._validate_semantic_binding_script(semantic_bindings, script)
        self._validate_semantic_binding_units(semantic_bindings, scenes)
        package_id = (
            manifest.get("package_id")
            or manifest.get("project_id")
            or scene_plan.get("project_id")
            or self._stable_package_id(source)
        )
        return PackageModel(
            root=package_root,
            package_id=str(package_id),
            scenes=scenes,
            script=script,
            manifest=manifest,
            scene_plan=scene_plan,
            semantic_bindings=semantic_bindings,
        )

    def _materialize(self, source: Path, workspace: Path) -> Path:
        workspace.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            return source
        if source.suffix.lower() != ".zip":
            raise InvalidPackageError("Final Package must be a directory or .zip")
        target = workspace / "package"
        if target.exists():
            shutil.rmtree(target)
        target.mkdir(parents=True)
        try:
            with zipfile.ZipFile(source) as archive:
                target_root = target.resolve()
                for member in archive.infolist():
                    member_path = Path(member.filename)
                    if member_path.is_absolute() or ".." in member_path.parts:
                        raise InvalidPackageError("unsafe path found inside Final Package")
                    member_target = (target / member.filename).resolve()
                    if target_root not in member_target.parents and member_target != target_root:
                        raise InvalidPackageError("unsafe path found inside Final Package")
                archive.extractall(target)
        except zipfile.BadZipFile as exc:
            raise InvalidPackageError("Final Package ZIP is invalid") from exc
        children = [item for item in target.iterdir() if item.name != "__MACOSX"]
        if len(children) == 1 and children[0].is_dir():
            return children[0]
        return target

    @staticmethod
    def _load_json(path: Path) -> dict:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise InvalidPackageError(f"invalid json: {path.name}") from exc
        if not isinstance(data, dict):
            raise InvalidPackageError(f"json root must be an object: {path.name}")
        return data

    def _load_semantic_bindings(self, root: Path, manifest: dict) -> dict:
        raw = manifest.get("semantic_bindings")
        candidates: list[Path] = []
        if isinstance(raw, str):
            candidate = (root / raw).resolve()
            if not self._inside(root, candidate):
                raise InvalidPackageError("semantic bindings path escapes Final Package")
            candidates.append(candidate)
        candidates.append(root / "semantic_bindings.json")

        for candidate in candidates:
            if not candidate.is_file():
                continue
            data = self._load_json(candidate)
            self._validate_semantic_bindings(data)
            return data
        return {}

    @staticmethod
    def _validate_semantic_bindings(data: dict) -> None:
        schema = data.get("schema_name")
        if schema is not None and schema not in _SEMANTIC_BINDING_SCHEMAS:
            raise InvalidPackageError("unsupported semantic bindings schema")
        asset_level = schema == "HEXA_ASSET_LEVEL_SEMANTIC_BINDINGS"
        if asset_level:
            semantic_intent = data.get("asset_is_semantic_intent_not_cutout")
            if semantic_intent is not None and semantic_intent is not True:
                raise InvalidPackageError(
                    "asset-level semantic bindings must describe semantic intent"
                )
            no_fixed_timing = data.get("no_fixed_timing")
            if no_fixed_timing is not None and no_fixed_timing is not True:
                raise InvalidPackageError(
                    "asset-level semantic bindings cannot own fixed timing"
                )

        scenes = data.get("scenes")
        if not isinstance(scenes, list):
            raise InvalidPackageError("semantic bindings scenes must be a list")

        seen_scenes: set[str] = set()
        for scene in scenes:
            if not isinstance(scene, dict):
                raise InvalidPackageError("semantic bindings scene must be an object")
            scene_id = scene.get("scene_id")
            if not isinstance(scene_id, str) or not scene_id.strip():
                raise InvalidPackageError("semantic bindings scene_id is required")
            if scene_id in seen_scenes:
                raise InvalidPackageError(f"duplicate semantic bindings scene: {scene_id}")
            seen_scenes.add(scene_id)

            assets = scene.get("assets")
            if not isinstance(assets, list):
                raise InvalidPackageError(
                    f"semantic bindings assets must be a list: {scene_id}"
                )
            seen_assets: set[str] = set()
            parent_by_asset: dict[str, str | None] = {}
            group_by_asset: dict[str, str] = {}
            phrase_by_group: dict[str, str] = {}
            for asset in assets:
                if not isinstance(asset, dict):
                    raise InvalidPackageError(
                        f"semantic binding asset must be an object: {scene_id}"
                    )
                asset_id = asset.get("asset_id")
                phrase = asset.get("script_text")
                if not isinstance(asset_id, str) or not asset_id.strip():
                    raise InvalidPackageError(
                        f"semantic binding asset_id is required: {scene_id}"
                    )
                if asset_id in seen_assets:
                    raise InvalidPackageError(
                        f"duplicate semantic binding asset: {scene_id}:{asset_id}"
                    )
                if not isinstance(phrase, str) or not phrase.strip():
                    raise InvalidPackageError(
                        f"semantic binding script_text is required: {scene_id}:{asset_id}"
                    )
                declared_scene = asset.get("scene_id")
                if declared_scene is not None and declared_scene != scene_id:
                    raise InvalidPackageError(
                        f"semantic binding scene mismatch: {scene_id}:{asset_id}"
                    )
                parent = asset.get("parent_asset_id")
                if parent is not None and not isinstance(parent, str):
                    raise InvalidPackageError(
                        f"semantic binding parent_asset_id must be a string: {scene_id}:{asset_id}"
                    )

                if asset_level:
                    binding_type = asset.get("binding_type")
                    if binding_type not in _ASSET_LEVEL_BINDING_TYPES:
                        raise InvalidPackageError(
                            f"invalid semantic binding type: {scene_id}:{asset_id}"
                        )
                    group_id = asset.get("semantic_group_id")
                    if not isinstance(group_id, str) or not group_id.strip():
                        raise InvalidPackageError(
                            f"semantic_group_id is required: {scene_id}:{asset_id}"
                        )
                    order = asset.get("sequence_order")
                    if isinstance(order, bool) or not isinstance(order, int) or order < 1:
                        raise InvalidPackageError(
                            f"sequence_order must be a positive integer: {scene_id}:{asset_id}"
                        )
                    confidence = asset.get("confidence")
                    if (
                        isinstance(confidence, bool)
                        or not isinstance(confidence, (int, float))
                        or not 0.0 <= float(confidence) <= 1.0
                    ):
                        raise InvalidPackageError(
                            f"confidence must be between 0 and 1: {scene_id}:{asset_id}"
                        )
                    locator = asset.get("visual_locator")
                    if locator is not None:
                        FinalPackageLoader._validate_visual_locator(
                            locator, scene_id=scene_id, asset_id=asset_id
                        )
                    group_by_asset[asset_id] = group_id
                    previous_phrase = phrase_by_group.setdefault(group_id, phrase.strip())
                    if previous_phrase != phrase.strip():
                        raise InvalidPackageError(
                            f"semantic group has inconsistent script_text: {scene_id}:{group_id}"
                        )

                seen_assets.add(asset_id)
                parent_by_asset[asset_id] = parent

            for asset_id, parent in parent_by_asset.items():
                if parent is not None and parent not in seen_assets:
                    raise InvalidPackageError(
                        f"semantic binding parent is missing: {scene_id}:{asset_id}"
                    )

            for asset_id in parent_by_asset:
                chain: set[str] = set()
                current: str | None = asset_id
                while current is not None:
                    if current in chain:
                        raise InvalidPackageError(
                            f"semantic binding parent cycle: {scene_id}:{asset_id}"
                        )
                    chain.add(current)
                    current = parent_by_asset.get(current)

            if asset_level:
                groups = scene.get("semantic_groups")
                if not isinstance(groups, list) or not groups:
                    raise InvalidPackageError(
                        f"asset-level semantic_groups are required: {scene_id}"
                    )
                declared_groups: dict[str, dict] = {}
                referenced_assets: set[str] = set()
                for group in groups:
                    if not isinstance(group, dict):
                        raise InvalidPackageError(
                            f"semantic group must be an object: {scene_id}"
                        )
                    group_id = group.get("semantic_group_id")
                    if not isinstance(group_id, str) or not group_id.strip():
                        raise InvalidPackageError(
                            f"semantic group id is required: {scene_id}"
                        )
                    if group_id in declared_groups:
                        raise InvalidPackageError(
                            f"duplicate semantic group: {scene_id}:{group_id}"
                        )
                    policy = group.get("animation_policy", "SEQUENTIAL_WITHIN_PHRASE")
                    if policy not in _SEMANTIC_GROUP_POLICIES:
                        raise InvalidPackageError(
                            f"unsupported semantic group policy: {scene_id}:{group_id}"
                        )
                    group_assets = group.get("asset_ids")
                    if not isinstance(group_assets, list) or not group_assets:
                        raise InvalidPackageError(
                            f"semantic group asset_ids are required: {scene_id}:{group_id}"
                        )
                    for asset_id in group_assets:
                        if asset_id not in seen_assets:
                            raise InvalidPackageError(
                                f"semantic group references missing asset: {scene_id}:{group_id}"
                            )
                        if group_by_asset.get(asset_id) != group_id:
                            raise InvalidPackageError(
                                f"semantic group membership mismatch: {scene_id}:{asset_id}"
                            )
                        if asset_id in referenced_assets:
                            raise InvalidPackageError(
                                f"semantic asset appears in multiple groups: {scene_id}:{asset_id}"
                            )
                        referenced_assets.add(asset_id)
                    group_phrase = group.get("script_text")
                    if (
                        not isinstance(group_phrase, str)
                        or group_phrase.strip() != phrase_by_group.get(group_id)
                    ):
                        raise InvalidPackageError(
                            f"semantic group script_text mismatch: {scene_id}:{group_id}"
                        )
                    declared_groups[group_id] = group
                if referenced_assets != seen_assets:
                    raise InvalidPackageError(
                        f"semantic groups must cover every semantic asset: {scene_id}"
                    )

    @staticmethod
    def _validate_visual_locator(locator: object, *, scene_id: str, asset_id: str) -> None:
        if not isinstance(locator, dict):
            raise InvalidPackageError(
                f"visual_locator must be an object: {scene_id}:{asset_id}"
            )
        coordinate_space = locator.get("coordinate_space", "normalized_scene")
        if coordinate_space != "normalized_scene":
            raise InvalidPackageError(
                f"visual_locator coordinate_space must be normalized_scene: "
                f"{scene_id}:{asset_id}"
            )
        values: dict[str, float] = {}
        for name in ("cx", "cy", "width", "height"):
            value = locator.get(name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise InvalidPackageError(
                    f"visual_locator {name} must be numeric: {scene_id}:{asset_id}"
                )
            values[name] = float(value)
        cx, cy = values["cx"], values["cy"]
        width, height = values["width"], values["height"]
        if not (0.0 <= cx <= 1.0 and 0.0 <= cy <= 1.0):
            raise InvalidPackageError(
                f"visual_locator center must be normalized: {scene_id}:{asset_id}"
            )
        if not (0.0 < width <= 1.0 and 0.0 < height <= 1.0):
            raise InvalidPackageError(
                f"visual_locator size must be normalized and positive: {scene_id}:{asset_id}"
            )
        epsilon = 1e-9
        if (
            cx - width / 2 < -epsilon
            or cx + width / 2 > 1.0 + epsilon
            or cy - height / 2 < -epsilon
            or cy + height / 2 > 1.0 + epsilon
        ):
            raise InvalidPackageError(
                f"visual_locator must stay inside scene bounds: {scene_id}:{asset_id}"
            )

    @staticmethod
    def _validate_scene_unit_visual_locators(scenes: list[SceneSource]) -> None:
        for scene in scenes:
            for unit in scene.units:
                if not isinstance(unit, dict) or unit.get("visual_locator") is None:
                    continue
                unit_id = str(unit.get("unit_id") or "unknown")
                FinalPackageLoader._validate_visual_locator(
                    unit["visual_locator"],
                    scene_id=scene.id,
                    asset_id=unit_id,
                )

    @staticmethod
    def _validate_semantic_binding_script(data: dict, script: str | None) -> None:
        if not data or not script:
            return
        for scene in data.get("scenes", []):
            if not isinstance(scene, dict):
                continue
            scene_id = str(scene.get("scene_id") or "")
            for asset in scene.get("assets", []):
                if not isinstance(asset, dict):
                    continue
                phrase = str(asset.get("script_text") or "").strip()
                if phrase and phrase not in script:
                    raise InvalidPackageError(
                        f"semantic binding script_text not found in canonical script: "
                        f"{scene_id}:{asset.get('asset_id')}"
                    )

    @staticmethod
    def _validate_semantic_binding_units(data: dict, scenes: list[SceneSource]) -> None:
        if data.get("schema_name") != "HEXA_ASSET_LEVEL_SEMANTIC_BINDINGS":
            return
        binding_scenes = {
            str(row.get("scene_id")): row
            for row in data.get("scenes", [])
            if isinstance(row, dict)
        }
        for scene in scenes:
            binding_scene = binding_scenes.get(scene.id)
            if binding_scene is None or not scene.units:
                continue
            unit_ids = {
                str(unit.get("unit_id"))
                for unit in scene.units
                if isinstance(unit, dict) and unit.get("unit_id")
            }
            missing = [
                str(asset.get("asset_id"))
                for asset in binding_scene.get("assets", [])
                if isinstance(asset, dict) and str(asset.get("asset_id")) not in unit_ids
            ]
            if missing:
                raise InvalidPackageError(
                    f"semantic asset intent missing from scene plan: {scene.id}:{missing[0]}"
                )

    def _load_scene_plan(self, root: Path, manifest: dict) -> dict:
        raw = manifest.get("scene_plan")
        candidates: list[Path] = []
        if isinstance(raw, str):
            candidate = (root / raw).resolve()
            if not self._inside(root, candidate):
                raise InvalidPackageError("scene plan path escapes Final Package")
            candidates.append(candidate)
        candidates.append(root / "scene_plan.json")
        for candidate in candidates:
            if candidate.is_file():
                return self._load_json(candidate)
        return {}

    def _load_script(self, root: Path, explicit: Path | None, manifest: dict) -> str | None:
        candidates: list[Path] = []
        if explicit:
            candidates.append(explicit.expanduser().resolve())
        for field in ("script", "canonical_script"):
            manifest_script = manifest.get(field)
            if not isinstance(manifest_script, str):
                continue
            candidate = (root / manifest_script).resolve()
            if self._inside(root, candidate) and candidate.exists():
                candidates.append(candidate)
                continue
            if field == "script" and ("\n" in manifest_script or len(manifest_script.split()) > 5):
                return manifest_script.strip()
        candidates.extend([root / "canonical_script.txt", root / "script.txt", root / "narration.txt"])
        for candidate in candidates:
            if candidate.exists() and candidate.is_file():
                return candidate.read_text(encoding="utf-8-sig").strip()
        return None

    def _discover_scenes(self, root: Path, manifest: dict, scene_plan: dict) -> list[SceneSource]:
        planned = scene_plan.get("scenes")
        if isinstance(planned, list):
            rows: list[SceneSource] = []
            for index, item in enumerate(planned):
                if not isinstance(item, dict):
                    continue
                raw_path = item.get("image") or item.get("path")
                if not isinstance(raw_path, str):
                    continue
                image = (root / raw_path).resolve()
                if not self._inside(root, image):
                    raise InvalidPackageError(f"scene path escapes Final Package: {raw_path}")
                if not image.is_file() or image.suffix.lower() not in _IMAGE_EXTENSIONS:
                    continue
                span = item.get("script_span") if isinstance(item.get("script_span"), dict) else {}
                rows.append(SceneSource(
                    id=str(item.get("scene_id") or item.get("id") or f"scene-{index + 1:03d}"),
                    image_path=image,
                    order=int(item.get("order", index + 1)) - 1,
                    title=item.get("title"),
                    narration_hint=span.get("text") or item.get("narration") or item.get("text"),
                    script_char_start=self._int_or_none(span.get("global_char_start")),
                    script_char_end=self._int_or_none(span.get("global_char_end")),
                    purpose=item.get("purpose"),
                    visual_concept=item.get("visual_concept"),
                    relation_to_previous=item.get("relation_to_previous"),
                    units=[row for row in item.get("units", []) if isinstance(row, dict)],
                    visual_progression=[
                        row for row in item.get("visual_progression", []) if isinstance(row, dict)
                    ],
                ))
            if rows:
                return sorted(rows, key=lambda row: row.order)

        declared = manifest.get("scenes")
        scenes: list[SceneSource] = []
        if isinstance(declared, list):
            for index, item in enumerate(declared):
                if not isinstance(item, dict):
                    continue
                raw_path = item.get("image") or item.get("path")
                if not isinstance(raw_path, str):
                    continue
                image = (root / raw_path).resolve()
                if not self._inside(root, image):
                    raise InvalidPackageError(f"scene path escapes Final Package: {raw_path}")
                if image.exists() and image.suffix.lower() in _IMAGE_EXTENSIONS:
                    scenes.append(SceneSource(
                        id=str(item.get("id") or f"scene-{index + 1:03d}"),
                        image_path=image,
                        order=index,
                        title=item.get("title"),
                        narration_hint=item.get("narration") or item.get("text"),
                    ))
        if scenes:
            return scenes
        scene_dirs = [root / "scenes", root / "images", root]
        images: list[Path] = []
        for directory in scene_dirs:
            if directory.exists():
                images = sorted(
                    p for p in directory.iterdir()
                    if p.is_file() and p.suffix.lower() in _IMAGE_EXTENSIONS
                )
                if images:
                    break
        return [
            SceneSource(id=f"scene-{i + 1:03d}", image_path=path, order=i)
            for i, path in enumerate(images)
        ]

    @staticmethod
    def _int_or_none(value) -> int | None:
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _inside(root: Path, candidate: Path) -> bool:
        root = root.resolve()
        candidate = candidate.resolve()
        return candidate == root or root in candidate.parents

    @staticmethod
    def _stable_package_id(source: Path) -> str:
        digest = hashlib.sha256(str(source).encode("utf-8")).hexdigest()[:12]
        return f"pkg-{digest}"
