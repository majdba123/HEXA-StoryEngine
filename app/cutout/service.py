from __future__ import annotations

import os
import shutil
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from app.models import PackageModel, VisualAsset
from app.shared.errors import StageFailedError
from app.vision.service import VisionObject

_IMAGE_EXTENSIONS = {".png", ".webp", ".jpg", ".jpeg"}


class CutoutService:
    def __init__(self, *, allow_scene_fallback: bool = False) -> None:
        self.allow_scene_fallback = allow_scene_fallback
        self._sam_backend = None
        self._sam_checked = False

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

        if detections:
            extracted = self._extract_detections(detections, output_dir)
            if extracted:
                return extracted

        if not self.allow_scene_fallback:
            raise StageFailedError(
                "No extractable assets were found in the Final Package",
                details={"code": "CUTOUT_BACKEND_REQUIRED", "detections": len(detections)},
            )

        # Development-only fallback. Production defaults to disabled because whole
        # scene posters are explicitly not an acceptable storytelling substitute.
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

    def _extract_detections(
        self,
        detections: list[VisionObject],
        output_dir: Path,
    ) -> list[VisualAsset]:
        backend = self._get_sam_backend()
        assets: list[VisualAsset] = []
        counters: dict[str, int] = {}
        for detection in detections:
            if detection.bbox is None:
                continue
            counters[detection.scene_id] = counters.get(detection.scene_id, 0) + 1
            number = counters[detection.scene_id]
            asset_id = f"{detection.scene_id}:asset-{number:02d}"
            target = output_dir / f"{detection.scene_id}-asset-{number:02d}.png"

            method = "white_background"
            image = None
            if backend is not None:
                try:
                    image = backend.cutout(detection.source_image, detection.bbox)
                    method = "sam2"
                except Exception:
                    image = None
            if image is None:
                image = self._boxed_cutout(detection.source_image, detection.bbox)
            if image.width < 2 or image.height < 2:
                continue
            image.save(target, format="PNG", optimize=True)
            assets.append(VisualAsset(
                id=asset_id,
                scene_id=detection.scene_id,
                role=detection.role,
                image_path=target,
                source_bbox=detection.bbox,
                confidence=detection.confidence,
                extraction_method=method,
            ))
        return assets

    def _get_sam_backend(self):
        if self._sam_checked:
            return self._sam_backend
        self._sam_checked = True
        checkpoint_raw = os.getenv("HEXA_SAM2_CHECKPOINT")
        if not checkpoint_raw:
            return None
        checkpoint = Path(checkpoint_raw).expanduser().resolve()
        if not checkpoint.is_file():
            return None
        try:
            from app.cutout.sam2 import SAM2CutoutBackend

            self._sam_backend = SAM2CutoutBackend(
                checkpoint,
                config=os.getenv("HEXA_SAM2_CONFIG") or None,
            )
        except Exception:
            self._sam_backend = None
        return self._sam_backend

    def _packaged_assets(self, package: PackageModel) -> list[VisualAsset]:
        declared = package.manifest.get("assets")
        if not isinstance(declared, list):
            return []
        root = package.root.resolve()
        assets: list[VisualAsset] = []
        for index, item in enumerate(declared):
            if not isinstance(item, dict):
                continue
            relative = item.get("path") or item.get("image")
            scene_id = item.get("scene_id")
            if not isinstance(relative, str) or not isinstance(scene_id, str):
                continue
            path = (root / relative).resolve()
            if root not in path.parents and path != root:
                raise StageFailedError("asset path escapes Final Package", details={"path": relative})
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

    @staticmethod
    def _boxed_cutout(
        source: Path,
        bbox: tuple[int, int, int, int],
    ) -> Image.Image:
        image = Image.open(source).convert("RGB")
        x, y, width, height = bbox
        x0 = max(0, x)
        y0 = max(0, y)
        x1 = min(image.width, x + max(1, width))
        y1 = min(image.height, y + max(1, height))
        crop = image.crop((x0, y0, x1, y1))
        rgb = np.asarray(crop)
        near_white = np.min(rgb, axis=2) >= 242
        binary = Image.fromarray(np.where(near_white, 0, 255).astype(np.uint8), mode="L")

        step = max(1, min(binary.width, binary.height) // 24)
        seeds: list[tuple[int, int]] = []
        for px in range(0, binary.width, step):
            seeds.extend([(px, 0), (px, binary.height - 1)])
        for py in range(0, binary.height, step):
            seeds.extend([(0, py), (binary.width - 1, py)])
        for seed in seeds:
            if binary.getpixel(seed) == 0:
                ImageDraw.floodfill(binary, seed, 128, thresh=0)

        marks = np.asarray(binary)
        alpha = np.full(marks.shape, 255, dtype=np.uint8)
        alpha[marks == 128] = 0
        alpha_image = Image.fromarray(alpha, mode="L").filter(ImageFilter.GaussianBlur(radius=0.55))
        rgba = crop.convert("RGBA")
        rgba.putalpha(alpha_image)
        visible = rgba.getchannel("A").getbbox()
        if visible is None:
            return rgba
        margin = 4
        left = max(0, visible[0] - margin)
        top = max(0, visible[1] - margin)
        right = min(rgba.width, visible[2] + margin)
        bottom = min(rgba.height, visible[3] + margin)
        return rgba.crop((left, top, right, bottom))
