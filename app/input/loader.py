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
        scenes = self._discover_scenes(package_root, manifest)
        if not scenes:
            raise InvalidPackageError("Final Package contains no scene images")
        package_id = manifest.get("package_id") or self._stable_package_id(source)
        return PackageModel(
            root=package_root,
            package_id=str(package_id),
            scenes=scenes,
            script=script,
            manifest=manifest,
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
            raise InvalidPackageError(f"invalid manifest: {path.name}") from exc
        if not isinstance(data, dict):
            raise InvalidPackageError("manifest root must be an object")
        return data

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

    def _discover_scenes(self, root: Path, manifest: dict) -> list[SceneSource]:
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
    def _inside(root: Path, candidate: Path) -> bool:
        root = root.resolve()
        candidate = candidate.resolve()
        return candidate == root or root in candidate.parents

    @staticmethod
    def _stable_package_id(source: Path) -> str:
        digest = hashlib.sha256(str(source).encode("utf-8")).hexdigest()[:12]
        return f"pkg-{digest}"
