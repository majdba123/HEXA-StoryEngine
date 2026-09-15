from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from app.models import PackageModel


@dataclass(frozen=True, slots=True)
class VisionObject:
    scene_id: str
    role: str
    bbox: tuple[int, int, int, int] | None
    confidence: float
    source_image: Path
    component_count: int = 1
    compound: bool = False
    area_ratio: float = 0.0
    seed_points: tuple[tuple[int, int], ...] = ()


def build_structural_foreground(bgr: np.ndarray) -> np.ndarray:
    """Build the strict foreground connectivity mask for HEXA scene art.

    The rule is deliberately geometry-only: two foreground regions are one object only
    when their structural pixels are physically connected. No semantic grouping,
    proximity grouping, containment grouping, or scene-level grouping is allowed here.

    We intentionally avoid morphological closing because closing can bridge a real
    white-space gap and violate that rule. Anti-aliased edge pixels are still retained
    by the HSV thresholds below.
    """
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    saturation = hsv[:, :, 1]
    value = hsv[:, :, 2]
    return (((saturation >= 18) | (value <= 220)).astype(np.uint8) * 255)


@dataclass(slots=True)
class _Component:
    label: int
    x: int
    y: int
    width: int
    height: int
    area: int
    contour: np.ndarray
    saturation: float
    value: float

    @property
    def x2(self) -> int:
        return self.x + self.width

    @property
    def y2(self) -> int:
        return self.y + self.height


class VisionService:
    """Discover independently animatable objects from strict visual connectivity.

    Background is removed conceptually first. Every surviving connected foreground
    island becomes an independent candidate. Semantic detection can *label* an island,
    but is never allowed to merge it with another island.
    """

    def __init__(self) -> None:
        self._florence = None
        self._florence_checked = False

    def analyze(self, package: PackageModel) -> list[VisionObject]:
        declared = self._declared_boxes(package)
        detector = self._get_florence()
        output: list[VisionObject] = []
        for scene in package.scenes:
            geometry = self._disconnected_objects(scene.id, scene.image_path)
            semantic_boxes = list(declared.get(scene.id, []))
            if detector is not None:
                try:
                    semantic_boxes.extend(detector.detect(scene.image_path))
                except Exception:
                    # Geometry remains authoritative if an optional semantic model fails.
                    pass
            output.extend(self._label_geometry(geometry, semantic_boxes))
        return output

    def _declared_boxes(
        self,
        package: PackageModel,
    ) -> dict[str, list[tuple[str, tuple[int, int, int, int], float]]]:
        by_scene: dict[str, list[tuple[str, tuple[int, int, int, int], float]]] = {}
        declared = package.manifest.get("objects", [])
        if not isinstance(declared, list):
            return by_scene
        valid_scenes = {scene.id for scene in package.scenes}
        for item in declared:
            if not isinstance(item, dict):
                continue
            scene_id = str(item.get("scene_id", ""))
            bbox = item.get("bbox")
            if scene_id not in valid_scenes or not isinstance(bbox, list) or len(bbox) != 4:
                continue
            parsed = tuple(int(v) for v in bbox)
            by_scene.setdefault(scene_id, []).append((
                str(item.get("role") or "object"),
                parsed,
                float(item.get("confidence", 1.0)),
            ))
        return by_scene

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

    def _disconnected_objects(self, scene_id: str, image_path: Path) -> list[VisionObject]:
        bgr = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
        if bgr is None:
            return []
        height, width = bgr.shape[:2]
        hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
        saturation = hsv[:, :, 1]
        value = hsv[:, :, 2]
        structural = build_structural_foreground(bgr)

        count, labels, stats, _ = cv2.connectedComponentsWithStats(structural, 8)
        frame_area = float(width * height)
        # Keep small but intentional animation cues such as arrows, lamps and badges.
        # Extremely tiny anti-alias/noise islands are still rejected.
        min_area = max(45, int(frame_area * 0.000022))
        components: list[_Component] = []
        for label in range(1, count):
            x, y, box_w, box_h, area = [int(v) for v in stats[label]]
            if area < min_area or box_w < 3 or box_h < 3:
                continue
            selected = labels[y:y + box_h, x:x + box_w] == label
            component_mask = selected.astype(np.uint8) * 255
            contours, _ = cv2.findContours(component_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            if not contours:
                continue
            contour = max(contours, key=cv2.contourArea).copy()
            contour[:, :, 0] += x
            contour[:, :, 1] += y
            sat_mean = float(saturation[y:y + box_h, x:x + box_w][selected].mean())
            val_mean = float(value[y:y + box_h, x:x + box_w][selected].mean())
            aspect = box_w / max(1, box_h)
            # A broad, low-saturation, very bright island is almost always a detached
            # soft shadow rather than an animation object. This filter never merges it
            # into a neighboring object; it simply excludes the background artifact.
            if sat_mean < 10 and val_mean > 210 and aspect > 2.1:
                continue
            components.append(_Component(
                label=label,
                x=x,
                y=y,
                width=box_w,
                height=box_h,
                area=area,
                contour=contour,
                saturation=sat_mean,
                value=val_mean,
            ))

        objects: list[VisionObject] = []
        margin = max(3, round(min(width, height) * 0.0045))
        for component in components:
            x0 = max(0, component.x - margin)
            y0 = max(0, component.y - margin)
            x1 = min(width, component.x2 + margin)
            y1 = min(height, component.y2 + margin)
            # A contour point is guaranteed to lie on this exact connected label and
            # is therefore a reliable seed for the strict cutout stage.
            seed = (int(component.contour[0, 0, 0]), int(component.contour[0, 0, 1]))
            objects.append(VisionObject(
                scene_id=scene_id,
                role="object",
                bbox=(x0, y0, x1 - x0, y1 - y0),
                confidence=0.76,
                source_image=image_path,
                component_count=1,
                compound=False,
                area_ratio=min(1.0, component.area / frame_area),
                seed_points=(seed,),
            ))

        objects.sort(key=lambda row: row.area_ratio, reverse=True)
        # Preserve more small cues than before. Story/Motion decide what to animate;
        # Vision's responsibility is to make every useful independent island available.
        limited = objects[:32]
        return [VisionObject(
            scene_id=row.scene_id,
            role="primary_visual" if index == 0 else f"support_visual_{index}",
            bbox=row.bbox,
            confidence=row.confidence,
            source_image=row.source_image,
            component_count=1,
            compound=False,
            area_ratio=row.area_ratio,
            seed_points=row.seed_points,
        ) for index, row in enumerate(limited)]

    @staticmethod
    def _label_geometry(
        geometry: list[VisionObject],
        semantic_boxes: list,
    ) -> list[VisionObject]:
        if not semantic_boxes:
            return geometry
        output: list[VisionObject] = []
        for row in geometry:
            best_role = row.role
            best_confidence = row.confidence
            best_iou = 0.0
            for semantic in semantic_boxes:
                role, bbox, confidence = semantic[0], semantic[1], semantic[2]
                iou = VisionService._iou(row.bbox, bbox)
                if iou > best_iou and iou >= 0.20:
                    best_iou = iou
                    best_role = str(role)
                    best_confidence = max(row.confidence, float(confidence))
            output.append(VisionObject(
                scene_id=row.scene_id,
                role=best_role,
                bbox=row.bbox,
                confidence=min(1.0, best_confidence),
                source_image=row.source_image,
                component_count=1,
                compound=False,
                area_ratio=row.area_ratio,
                seed_points=row.seed_points,
            ))
        return output

    @staticmethod
    def _iou(a, b) -> float:
        if not a or not b:
            return 0.0
        ax, ay, aw, ah = a
        bx, by, bw, bh = [int(v) for v in b]
        x0, y0 = max(ax, bx), max(ay, by)
        x1, y1 = min(ax + aw, bx + bw), min(ay + ah, by + bh)
        if x1 <= x0 or y1 <= y0:
            return 0.0
        inter = (x1 - x0) * (y1 - y0)
        union = aw * ah + bw * bh - inter
        return inter / max(1, union)
