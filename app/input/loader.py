from __future__ import annotations

import hashlib
import json
import shutil
import zipfile
from pathlib import Path

from app.models import PackageModel, SceneSource
from app.shared.errors import InvalidPackageError

_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}


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
        if schema is not None and schema != "HEXA_SEMANTIC_BINDINGS":
            raise InvalidPackageError("unsupported semantic bindings schema")
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
                seen_assets.add(asset_id)
                parent_by_asset[asset_id] = parent

            for asset_id, parent in parent_by_asset.items():
                if parent is not None and parent not in seen_assets:
                    raise InvalidPackageError(
                        f"semantic binding parent is missing: {scene_id}:{asset_id}"
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
