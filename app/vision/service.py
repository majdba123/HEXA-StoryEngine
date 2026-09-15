from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.models import PackageModel


@dataclass(frozen=True, slots=True)
class VisionObject:
    scene_id: str
    role: str
    bbox: tuple[int, int, int, int] | None
    confidence: float
    source_image: Path


class VisionService:
    """Semantic vision boundary.

    V2 intentionally keeps model-specific code behind this boundary. The baseline reads
    explicit object declarations from the Final Package. Florence/SAM adapters can add
    detections without changing downstream stages.
    """

    def analyze(self, package: PackageModel) -> list[VisionObject]:
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
