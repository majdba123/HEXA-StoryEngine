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
    """Return the structural foreground mask used by discovery and cutout.

    Keeping this function shared is important: cutout seeds must resolve to the exact
    connected components discovered by Vision, otherwise close neighboring objects can
    leak into one another's matte.
    """
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    saturation = hsv[:, :, 1]
    value = hsv[:, :, 2]
    structural = ((saturation >= 18) | (value <= 238)).astype(np.uint8) * 255
    return cv2.morphologyEx(
        structural,
        cv2.MORPH_CLOSE,
        np.ones((3, 3), dtype=np.uint8),
        iterations=1,
    )


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

    @property
    def center(self) -> tuple[float, float]:
        return (self.x + self.width / 2, self.y + self.height / 2)


class VisionService:
    """Discover motion-safe visual objects.

    Geometry is authoritative: foreground islands separated by real background space
    become independent object candidates. Small detached pieces that are clearly
    enclosed by or tightly associated with a larger illustration are grouped back into
    that compound object. Semantic detectors may label geometry, but they never merge
    distant objects merely because they share a semantic class.
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
                    pass
            output.extend(self._label_geometry(geometry, semantic_boxes))
        return output

    def _declared_boxes(self, package: PackageModel) -> dict[str, list[tuple[str, tuple[int, int, int, int], float]]]:
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

        # Structural foreground deliberately rejects faint neutral drop-shadows while
        # retaining black outlines, colored art, arrows, labels, and small badges.
        structural = build_structural_foreground(bgr)

        count, labels, stats, _ = cv2.connectedComponentsWithStats(structural, 8)
        frame_area = float(width * height)
        min_area = max(70, int(frame_area * 0.000045))
        components: list[_Component] = []
        for label in range(1, count):
            x, y, box_w, box_h, area = [int(v) for v in stats[label]]
            if area < min_area or box_w < 3 or box_h < 3:
                continue
            component_mask = (labels[y:y + box_h, x:x + box_w] == label).astype(np.uint8) * 255
            contours, _ = cv2.findContours(component_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            if not contours:
                continue
            contour = max(contours, key=cv2.contourArea).copy()
            contour[:, :, 0] += x
            contour[:, :, 1] += y
            selected = labels[y:y + box_h, x:x + box_w] == label
            sat_mean = float(saturation[y:y + box_h, x:x + box_w][selected].mean())
            val_mean = float(value[y:y + box_h, x:x + box_w][selected].mean())
            aspect = box_w / max(1, box_h)
            # Soft broad neutral shadows are not independent visual objects.
            if sat_mean < 11 and val_mean > 205 and aspect > 2.0:
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

        groups = self._group_compound_parts(components, width, height)
        objects: list[VisionObject] = []
        for index, group in enumerate(groups):
            x0 = min(c.x for c in group)
            y0 = min(c.y for c in group)
            x1 = max(c.x2 for c in group)
            y1 = max(c.y2 for c in group)
            margin = max(4, round(min(width, height) * 0.006))
            x0 = max(0, x0 - margin)
            y0 = max(0, y0 - margin)
            x1 = min(width, x1 + margin)
            y1 = min(height, y1 + margin)
            total_area = sum(c.area for c in group)
            objects.append(VisionObject(
                scene_id=scene_id,
                role="primary_visual" if index == 0 else f"support_visual_{index}",
                bbox=(x0, y0, x1 - x0, y1 - y0),
                confidence=0.72 if len(group) == 1 else 0.68,
                source_image=image_path,
                component_count=len(group),
                compound=len(group) > 1,
                area_ratio=min(1.0, total_area / frame_area),
                seed_points=tuple((int(c.contour[0, 0, 0]), int(c.contour[0, 0, 1])) for c in group),
            ))
        objects.sort(key=lambda row: row.area_ratio, reverse=True)
        # Restore deterministic primary/support roles after sorting.
        return [VisionObject(
            scene_id=row.scene_id,
            role="primary_visual" if i == 0 else f"support_visual_{i}",
            bbox=row.bbox,
            confidence=row.confidence,
            source_image=row.source_image,
            component_count=row.component_count,
            compound=row.compound,
            area_ratio=row.area_ratio,
            seed_points=row.seed_points,
        ) for i, row in enumerate(objects[:12])]

    def _group_compound_parts(
        self,
        components: list[_Component],
        frame_width: int,
        frame_height: int,
    ) -> list[list[_Component]]:
        if not components:
            return []
        parent = list(range(len(components)))

        def find(i: int) -> int:
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        def union(a: int, b: int) -> None:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[rb] = ra

        # Closed-outline containment is a strong compound signal: a thought bubble
        # enclosing its content, or a barrier/sign enclosing internal visual parts.
        for i, outer in enumerate(components):
            if outer.width * outer.height < frame_width * frame_height * 0.002:
                continue
            for j, inner in enumerate(components):
                if i == j or inner.area >= outer.area:
                    continue
                cx, cy = inner.center
                inside = cv2.pointPolygonTest(outer.contour.astype(np.float32), (cx, cy), False)
                if inside >= 0:
                    union(i, j)

        # Very small nearby satellites belong to a larger compound illustration.
        # Medium standalone arrows/badges intentionally remain separate.
        max_satellite_gap = max(14.0, min(frame_width, frame_height) * 0.055)
        ordered = sorted(range(len(components)), key=lambda idx: components[idx].area, reverse=True)
        for small_idx in reversed(ordered):
            small = components[small_idx]
            best_idx = None
            best_gap = float("inf")
            for large_idx in ordered:
                large = components[large_idx]
                if large.area <= small.area:
                    continue
                ratio = small.area / max(1, large.area)
                if ratio > 0.075:
                    continue
                gap = self._bbox_gap(small, large)
                if gap < best_gap:
                    best_gap = gap
                    best_idx = large_idx
            if best_idx is not None and best_gap <= max_satellite_gap:
                union(best_idx, small_idx)

        grouped: dict[int, list[_Component]] = {}
        for idx, component in enumerate(components):
            grouped.setdefault(find(idx), []).append(component)
        groups = list(grouped.values())
        groups.sort(key=lambda group: sum(c.area for c in group), reverse=True)
        return groups

    @staticmethod
    def _bbox_gap(a: _Component, b: _Component) -> float:
        dx = max(b.x - a.x2, a.x - b.x2, 0)
        dy = max(b.y - a.y2, a.y - b.y2, 0)
        return float((dx * dx + dy * dy) ** 0.5)

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
                if len(semantic) == 3 and isinstance(semantic[0], str):
                    role, bbox, confidence = semantic
                else:
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
                component_count=row.component_count,
                compound=row.compound,
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
