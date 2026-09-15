from __future__ import annotations

import shutil
from pathlib import Path

from app.models import PackageModel, VisualAsset
from app.shared.errors import StageFailedError
from app.vision.service import VisionObject

_IMAGE_EXTENSIONS = {".png", ".webp"}


class CutoutService:
    def __init__(self, *, allow_scene_fallback: bool = False) -> None:
        self.allow_scene_fallback = allow_scene_fallback

    def extract(
        self,
        package: PackageModel,
        detections: list[VisionObject],
        workspace: Path,
    ) -> list[VisualAsset]:
        output_dir = workspace / "assets"
        output_dir.mkdir(parents=True, exist_ok=True)
        packaged = self._packaged_assets(package)
        if packaged:
            return packaged
        # The baseline only accepts explicit packaged cutouts. AI segmentation adapters
        # will populate this same contract. Scene fallback is opt-in for development only.
        if not self.allow_scene_fallback:
            raise StageFailedError(
                "Final Package has no extracted assets; configure the segmentation backend",
                details={"code": "CUTOUT_BACKEND_REQUIRED", "detections": len(detections)},
            )
        assets: list[VisualAsset] = []
        for scene in package.scenes:
            target = output_dir / f"{scene.id}{scene.image_path.suffix.lower()}"
            shutil.copy2(scene.image_path, target)
            assets.append(VisualAsset(
                id=f"{scene.id}:scene",
                scene_id=scene.id,
                role="scene_reference",
                image_path=target,
                extraction_method="scene_fallback",
            ))
        return assets

    def _packaged_assets(self, package: PackageModel) -> list[VisualAsset]:
        declared = package.manifest.get("assets")
        if not isinstance(declared, list):
            return []
        assets: list[VisualAsset] = []
        for index, item in enumerate(declared):
            if not isinstance(item, dict):
                continue
            relative = item.get("path") or item.get("image")
            scene_id = item.get("scene_id")
            if not isinstance(relative, str) or not isinstance(scene_id, str):
                continue
            path = (package.root / relative).resolve()
            if not path.exists() or path.suffix.lower() not in _IMAGE_EXTENSIONS:
                continue
            bbox = item.get("bbox")
            parsed_bbox = tuple(int(v) for v in bbox) if isinstance(bbox, list) and len(bbox) == 4 else None
            assets.append(VisualAsset(
                id=str(item.get("id") or f"asset-{index + 1:03d}"),
                scene_id=scene_id,
                role=str(item.get("role") or "object"),
                image_path=path,
                source_bbox=parsed_bbox,
                confidence=float(item.get("confidence", 1.0)),
                extraction_method="final_package",
            ))
        return assets
