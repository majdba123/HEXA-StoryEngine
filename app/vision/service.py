from __future__ import annotations

import os
from collections import deque
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

from app.models import PackageModel


@dataclass(frozen=True, slots=True)
class VisionObject:
    scene_id: str
    role: str
    bbox: tuple[int, int, int, int] | None
    confidence: float
    source_image: Path


class VisionService:
    """Discover only top-level, clearly separated visual groups.

    This fallback is intentionally conservative. It is not an object-segmentation
    engine: nearby details remain one authored visual group. Only large groups that
    are visibly separated by meaningful whitespace are exposed independently.
    """

    def __init__(self) -> None:
        self._florence = None
        self._florence_checked = False

    def analyze(self, package: PackageModel) -> list[VisionObject]:
        declared = self._declared(package)
        if declared:
            return declared

        detector = self._get_florence()
        output: list[VisionObject] = []
        for scene in package.scenes:
            rows: list[VisionObject] = []
            if detector is not None:
                try:
                    for label, bbox, confidence in detector.detect(scene.image_path):
                        rows.append(VisionObject(
                            scene_id=scene.id,
                            role=label,
                            bbox=bbox,
                            confidence=confidence,
                            source_image=scene.image_path,
                        ))
                except Exception:
                    rows = []
            if not rows:
                rows = self._visual_groups(scene.id, scene.image_path)
            output.extend(rows)
        return output

    def _declared(self, package: PackageModel) -> list[VisionObject]:
        by_scene = {scene.id: scene for scene in package.scenes}
        declared = package.manifest.get("objects", [])
        output: list[VisionObject] = []
        if isinstance(declared, list):
            for item in declared:
                if not isinstance(item, dict):
                    continue
                scene_id = str(item.get("scene_id", ""))
                scene = by_scene.get(scene_id)
                if not scene:
                    continue
                bbox = item.get("bbox")
                parsed_bbox = None
                if isinstance(bbox, list) and len(bbox) == 4:
                    parsed_bbox = tuple(int(v) for v in bbox)
                output.append(VisionObject(
                    scene_id=scene_id,
                    role=str(item.get("role") or "object"),
                    bbox=parsed_bbox,
                    confidence=float(item.get("confidence", 1.0)),
                    source_image=scene.image_path,
                ))
        return output

    def _get_florence(self):
        if self._florence_checked:
            return self._florence
        self._florence_checked = True
        raw = os.getenv("HEXA_FLORENCE_MODEL")
        if not raw:
            return None
        model_path = Path(raw).expanduser().resolve()
        if not model_path.exists():
            return None
        try:
            from app.vision.florence import FlorenceDetector

            self._florence = FlorenceDetector(model_path)
        except Exception:
            self._florence = None
        return self._florence

    def _visual_groups(self, scene_id: str, image_path: Path) -> list[VisionObject]:
        image = np.asarray(Image.open(image_path).convert("RGB"))
        height, width = image.shape[:2]
        canvas_area = max(1, width * height)

        foreground = np.min(image, axis=2) < 244
        block = 12
        rows = (height + block - 1) // block
        cols = (width + block - 1) // block
        padded = np.zeros((rows * block, cols * block), dtype=bool)
        padded[:height, :width] = foreground
        low = padded.reshape(rows, block, cols, block).any(axis=(1, 3))
        low = self._dilate(low, iterations=3)

        visited = np.zeros_like(low, dtype=bool)
        boxes: list[tuple[int, int, int, int, int]] = []
        for y in range(rows):
            for x in range(cols):
                if not low[y, x] or visited[y, x]:
                    continue
                queue = deque([(x, y)])
                visited[y, x] = True
                min_x = max_x = x
                min_y = max_y = y
                cells = 0
                while queue:
                    cx, cy = queue.popleft()
                    cells += 1
                    min_x, max_x = min(min_x, cx), max(max_x, cx)
                    min_y, max_y = min(min_y, cy), max(max_y, cy)
                    for nx in range(max(0, cx - 1), min(cols, cx + 2)):
                        for ny in range(max(0, cy - 1), min(rows, cy + 2)):
                            if low[ny, nx] and not visited[ny, nx]:
                                visited[ny, nx] = True
                                queue.append((nx, ny))

                if cells < 6:
                    continue
                x0 = max(0, min_x * block - 18)
                y0 = max(0, min_y * block - 18)
                x1 = min(width, (max_x + 1) * block + 18)
                y1 = min(height, (max_y + 1) * block + 18)
                box_w = x1 - x0
                box_h = y1 - y0
                area = box_w * box_h
                area_ratio = area / canvas_area
                foreground_ratio = int(foreground[y0:y1, x0:x1].sum()) / canvas_area
                substantial_shape = (
                    (box_w / width >= 0.10 and box_h / height >= 0.16)
                    or (box_w / width >= 0.18 and box_h / height >= 0.10)
                )
                if area_ratio < 0.018 or foreground_ratio < 0.008 or not substantial_shape:
                    continue
                boxes.append((area, x0, y0, x1, y1))

        boxes.sort(reverse=True)
        output: list[VisionObject] = []
        for index, (_, x0, y0, x1, y1) in enumerate(boxes[:4]):
            output.append(VisionObject(
                scene_id=scene_id,
                role="primary_visual" if index == 0 else f"support_visual_{index}",
                bbox=(x0, y0, x1 - x0, y1 - y0),
                confidence=0.58,
                source_image=image_path,
            ))

        if not output:
            output.append(VisionObject(
                scene_id=scene_id,
                role="primary_visual",
                bbox=(0, 0, width, height),
                confidence=0.50,
                source_image=image_path,
            ))
        return output

    @staticmethod
    def _dilate(mask: np.ndarray, iterations: int) -> np.ndarray:
        result = mask.copy()
        for _ in range(iterations):
            padded = np.pad(result, 1, mode="constant")
            merged = np.zeros_like(result)
            for dy in range(3):
                for dx in range(3):
                    merged |= padded[dy:dy + result.shape[0], dx:dx + result.shape[1]]
            result = merged
        return result
