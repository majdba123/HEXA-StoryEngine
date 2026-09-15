from __future__ import annotations

import os
import shutil
from collections import deque
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

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
            image.save(target, format="PNG", optimize=False, compress_level=3)
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
        context_margin = max(8, round(min(max(1, width), max(1, height)) * 0.06))
        x0 = max(0, x - context_margin)
        y0 = max(0, y - context_margin)
        x1 = min(image.width, x + max(1, width) + context_margin)
        y1 = min(image.height, y + max(1, height) + context_margin)
        crop = image.crop((x0, y0, x1, y1))
        rgb = np.asarray(crop)

        # Only white pixels connected to the crop boundary are background. This
        # preserves white details inside icons/characters while reliably removing
        # the white HEXA scene canvas around the object.
        near_white = np.min(rgb, axis=2) >= 242
        background = CutoutService._border_connected_background(near_white)
        alpha = np.full(near_white.shape, 255, dtype=np.uint8)
        alpha[background] = 0
        alpha_image = Image.fromarray(alpha).filter(ImageFilter.GaussianBlur(radius=0.55))

        rgba = crop.convert("RGBA")
        rgba.putalpha(alpha_image)
        visible = rgba.getchannel("A").getbbox()
        if visible is None:
            return rgba

        # Keep a transparent safety margin so later scaling/animation never grows a
        # white fringe at the object boundary.
        margin = 6
        left = max(0, visible[0] - margin)
        top = max(0, visible[1] - margin)
        right = min(rgba.width, visible[2] + margin)
        bottom = min(rgba.height, visible[3] + margin)
        return rgba.crop((left, top, right, bottom))

    @staticmethod
    def _border_connected_background(near_white: np.ndarray) -> np.ndarray:
        """Return border-connected white background without full-resolution Python flood fill.

        Large Final Package scenes can contain millions of pixels. Flood-filling every
        source pixel in Python is prohibitively slow, so connectivity is solved on an
        adaptive coarse mask and then projected back onto the exact near-white mask.
        Only pixels that are actually near-white can become transparent at full
        resolution, which preserves colored edges and keeps the fallback deterministic.
        """
        height, width = near_white.shape
        if height == 0 or width == 0:
            return np.zeros_like(near_white, dtype=bool)

        target_cells = 80_000
        block = max(1, int(np.ceil(np.sqrt((height * width) / target_cells))))
        if block == 1:
            low = near_white
        else:
            rows = (height + block - 1) // block
            cols = (width + block - 1) // block
            padded = np.zeros((rows * block, cols * block), dtype=np.float32)
            padded[:height, :width] = near_white
            coverage = padded.reshape(rows, block, cols, block).mean(axis=(1, 3))
            low = coverage >= 0.70

        low_h, low_w = low.shape
        connected = np.zeros_like(low, dtype=bool)
        queue: deque[tuple[int, int]] = deque()

        def seed(x: int, y: int) -> None:
            if low[y, x] and not connected[y, x]:
                connected[y, x] = True
                queue.append((x, y))

        for x in range(low_w):
            seed(x, 0)
            if low_h > 1:
                seed(x, low_h - 1)
        for y in range(low_h):
            seed(0, y)
            if low_w > 1:
                seed(low_w - 1, y)

        while queue:
            x, y = queue.popleft()
            if x > 0 and low[y, x - 1] and not connected[y, x - 1]:
                connected[y, x - 1] = True
                queue.append((x - 1, y))
            if x + 1 < low_w and low[y, x + 1] and not connected[y, x + 1]:
                connected[y, x + 1] = True
                queue.append((x + 1, y))
            if y > 0 and low[y - 1, x] and not connected[y - 1, x]:
                connected[y - 1, x] = True
                queue.append((x, y - 1))
            if y + 1 < low_h and low[y + 1, x] and not connected[y + 1, x]:
                connected[y + 1, x] = True
                queue.append((x, y + 1))

        if block == 1:
            return connected

        expanded = np.repeat(np.repeat(connected, block, axis=0), block, axis=1)[:height, :width]
        return expanded & near_white
