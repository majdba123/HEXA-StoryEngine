from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from app.models import VisualAsset
from app.shared.errors import StageFailedError


@dataclass(frozen=True, slots=True)
class _Candidate:
    label: int
    dominant_label: int
    side: str
    area_ratio: float
    center_distance: float
    bbox: tuple[int, int, int, int]


class RefinementService:
    """Conservative post-Cutout splitter for one obvious isolated secondary visual.

    Cutout Pass 1 is the protected authority. Refinement never re-runs scene
    segmentation and never changes Pass-1 files. It only inspects an approved RGBA
    asset and, when geometric evidence is strong and unambiguous, partitions one large
    edge-isolated secondary lobe from the parent.

    Both derived PNGs keep the *same canvas* and source geometry as their Pass-1
    parent. Therefore compositing them at the same settled transform reconstructs the
    Pass-1 visual pixel-for-pixel. If confidence is not high, the exact original
    VisualAsset object is passed through unchanged.
    """

    _MIN_PARENT_AREA_RATIO = 0.20
    _MIN_CORE_SHARE = 0.10
    _MAX_CORE_SHARE = 0.33
    _MIN_HEIGHT_SHARE = 0.52
    _MIN_WIDTH_SHARE = 0.10
    _MAX_WIDTH_SHARE = 0.36
    _MIN_ASPECT = 1.35
    _MIN_CENTER_DISTANCE = 0.35
    _EDGE_FRACTION = 0.18
    _MIN_DERIVED_ALPHA_SHARE = 0.08
    _MAX_DERIVED_ALPHA_SHARE = 0.38

    def refine(self, assets: list[VisualAsset], workspace: Path) -> list[VisualAsset]:
        output_dir = workspace / "refinement"
        output_dir.mkdir(parents=True, exist_ok=True)

        output: list[VisualAsset] = []
        for asset in assets:
            derived = self._refine_asset(asset, output_dir)
            output.extend(derived if derived is not None else [asset])
        return output

    def _refine_asset(
        self,
        asset: VisualAsset,
        output_dir: Path,
    ) -> list[VisualAsset] | None:
        if (asset.source_area_ratio or 0.0) < self._MIN_PARENT_AREA_RATIO:
            return None
        if not asset.image_path.is_file():
            raise StageFailedError(
                "refinement input asset is missing",
                details={"asset_id": asset.id, "path": str(asset.image_path)},
            )

        with Image.open(asset.image_path) as opened:
            rgba = np.asarray(opened.convert("RGBA"))
        if rgba.shape[0] < 80 or rgba.shape[1] < 80:
            return None

        candidate, core_labels = self._find_candidate(rgba)
        if candidate is None:
            return None

        satellite_mask = self._partition_satellite(rgba, core_labels, candidate)
        if satellite_mask is None:
            return None

        original_alpha = rgba[:, :, 3]
        visible = original_alpha > 0
        visible_count = int(np.count_nonzero(visible))
        satellite_visible = satellite_mask & visible
        satellite_count = int(np.count_nonzero(satellite_visible))
        if visible_count <= 0:
            return None
        satellite_share = satellite_count / visible_count
        if not (self._MIN_DERIVED_ALPHA_SHARE <= satellite_share <= self._MAX_DERIVED_ALPHA_SHARE):
            return None

        satellite_rgba = rgba.copy()
        main_rgba = rgba.copy()
        satellite_rgba[:, :, 3] = np.where(satellite_visible, original_alpha, 0).astype(np.uint8)
        main_rgba[:, :, 3] = np.where(satellite_visible, 0, original_alpha).astype(np.uint8)
        if not np.any(main_rgba[:, :, 3]) or not np.any(satellite_rgba[:, :, 3]):
            return None

        reconstructed_alpha = np.maximum(main_rgba[:, :, 3], satellite_rgba[:, :, 3])
        if not np.array_equal(reconstructed_alpha, original_alpha):
            return None
        if np.any((main_rgba[:, :, 3] > 0) & (satellite_rgba[:, :, 3] > 0)):
            return None

        safe_name = asset.id.replace(":", "-").replace("/", "-")
        main_path = output_dir / f"{safe_name}-main.png"
        secondary_path = output_dir / f"{safe_name}-secondary.png"
        Image.fromarray(main_rgba, mode="RGBA").save(
            main_path,
            format="PNG",
            optimize=False,
            compress_level=3,
        )
        Image.fromarray(satellite_rgba, mode="RGBA").save(
            secondary_path,
            format="PNG",
            optimize=False,
            compress_level=3,
        )

        parent_ratio = asset.source_area_ratio or 0.0
        main_share = 1.0 - satellite_share
        main = asset.model_copy(update={
            "image_path": main_path,
            "source_area_ratio": parent_ratio * main_share,
            "extraction_method": f"{asset.extraction_method}+refined_main",
            "asset_family_id": asset.asset_family_id or asset.id,
            "render_as_family_canvas": True,
        })
        secondary = asset.model_copy(update={
            "id": f"{asset.id}:secondary-01",
            "role": "secondary_object",
            "image_path": secondary_path,
            "source_area_ratio": parent_ratio * satellite_share,
            "confidence": min(asset.confidence, 0.96),
            "extraction_method": f"{asset.extraction_method}+refined_secondary",
            "independent": True,
            "compound": False,
            "component_count": 1,
            "can_animate_independently": True,
            "parent_asset_id": asset.id,
            "asset_family_id": asset.asset_family_id or asset.id,
            "render_as_family_canvas": True,
        })
        return [main, secondary]

    def _find_candidate(self, rgba: np.ndarray) -> tuple[_Candidate | None, np.ndarray]:
        height, width = rgba.shape[:2]
        alpha = rgba[:, :, 3]
        rgb = rgba[:, :, :3]
        hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)

        core = (
            (alpha >= 32)
            & ((hsv[:, :, 1] >= 30) | (hsv[:, :, 2] <= 225))
        ).astype(np.uint8) * 255
        kernel_size = max(3, min(21, int(round(min(height, width) * 0.02))))
        if kernel_size % 2 == 0:
            kernel_size += 1
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel_size, kernel_size))
        opened = cv2.morphologyEx(core, cv2.MORPH_OPEN, kernel)

        count, labels, stats, centers = cv2.connectedComponentsWithStats(opened, connectivity=8)
        if count <= 2:
            return None, labels
        areas = stats[1:, cv2.CC_STAT_AREA]
        if not np.any(areas > 0):
            return None, labels
        dominant_label = int(np.argmax(areas)) + 1
        dominant_center = centers[dominant_label]
        total_core = float(np.count_nonzero(opened))
        diagonal = float((width * width + height * height) ** 0.5)
        if total_core <= 0 or diagonal <= 0:
            return None, labels

        candidates: list[tuple[float, _Candidate]] = []
        for label in range(1, count):
            if label == dominant_label:
                continue
            x, _y, box_w, box_h, area = [int(v) for v in stats[label]]
            if area <= 0:
                continue
            area_ratio = area / total_core
            width_share = box_w / width
            height_share = box_h / height
            aspect = box_h / max(1, box_w)
            left_edge = x / width <= self._EDGE_FRACTION
            right_edge = (x + box_w) / width >= 1.0 - self._EDGE_FRACTION
            if not (left_edge or right_edge):
                continue
            if not (self._MIN_CORE_SHARE <= area_ratio <= self._MAX_CORE_SHARE):
                continue
            if height_share < self._MIN_HEIGHT_SHARE:
                continue
            if not (self._MIN_WIDTH_SHARE <= width_share <= self._MAX_WIDTH_SHARE):
                continue
            if aspect < self._MIN_ASPECT:
                continue

            center = centers[label]
            center_distance = float(np.linalg.norm(center - dominant_center) / diagonal)
            if center_distance < self._MIN_CENTER_DISTANCE:
                continue
            side = "left" if center[0] < dominant_center[0] else "right"
            score = center_distance + height_share * 0.35 + area_ratio * 0.20
            candidates.append((score, _Candidate(
                label, dominant_label, side, area_ratio, center_distance,
                (x, _y, box_w, box_h),
            )))

        if len(candidates) != 1:
            return None, labels
        return candidates[0][1], labels

    @staticmethod
    def _partition_satellite(
        rgba: np.ndarray,
        core_labels: np.ndarray,
        candidate: _Candidate,
    ) -> np.ndarray | None:
        """Extract a whole isolated side object, otherwise preserve Pass 1.

        Refinement is allowed only when the candidate and the dominant illustration
        have an actual horizontal background gutter. This rejects overlapping/touching
        characters even when morphology can visually separate their colored cores.
        Once a gutter exists, the complete edge-side object is recovered with the same
        border-background rule as Pass 1 so white faces, shoes, internal labels, and
        antialiasing stay attached to the object.
        """
        height, width = rgba.shape[:2]
        alpha = rgba[:, :, 3]
        rgb = rgba[:, :, :3]
        candidate_core = core_labels == candidate.label
        dominant_core = core_labels == candidate.dominant_label
        if not np.any(candidate_core) or not np.any(dominant_core):
            return None

        candidate_ys, candidate_xs = np.where(candidate_core)
        dominant_ys, dominant_xs = np.where(dominant_core)
        if candidate_xs.size == 0 or dominant_xs.size == 0:
            return None

        if candidate.side == "right":
            gap_start = int(dominant_xs.max()) + 1
            gap_end = int(candidate_xs.min())
        else:
            gap_start = int(candidate_xs.max()) + 1
            gap_end = int(dominant_xs.min())

        gap_width = gap_end - gap_start
        min_gap = max(12, round(width * 0.014))
        if gap_width < min_gap:
            return None

        visible_ink = (alpha >= 12) & (np.min(rgb, axis=2) < 242)
        search_start = max(1, gap_start)
        search_end = min(width - 1, gap_end)
        if search_end <= search_start:
            return None
        band_y0 = max(0, round(height * 0.05))
        band_y1 = min(height, round(height * 0.85))
        separator = (search_start + search_end) // 2
        moat = max(4, round(width * 0.006))
        moat_x0 = max(0, separator - moat)
        moat_x1 = min(width, separator + moat + 1)
        moat_band = visible_ink[band_y0:band_y1, moat_x0:moat_x1]
        if moat_band.size == 0 or float(moat_band.mean()) > 0.035:
            return None

        candidate_edge = int(candidate_xs.min()) if candidate.side == "right" else int(candidate_xs.max())
        clearance = candidate_edge - separator if candidate.side == "right" else separator - candidate_edge
        safe_margin = max(10, round(width * 0.008))
        if clearance < safe_margin:
            return None

        if candidate.side == "right":
            region_x0, region_x1 = separator + 1, width
        else:
            region_x0, region_x1 = 0, separator
        if region_x1 - region_x0 < 8:
            return None

        region_rgb = rgb[:, region_x0:region_x1]
        region_alpha = alpha[:, region_x0:region_x1]
        near_white = np.min(region_rgb, axis=2) >= 242
        background_like = (region_alpha < 12) | near_white

        open_space = background_like.astype(np.uint8) * 255
        flood = open_space.copy()
        flood_mask = np.zeros((height + 2, flood.shape[1] + 2), dtype=np.uint8)
        cv2.floodFill(flood, flood_mask, (0, 0), 128)
        outside = flood == 128
        local_object = (~outside) & (region_alpha > 0)
        if not np.any(local_object):
            return None

        local_core = candidate_core[:, region_x0:region_x1]
        core_count = int(np.count_nonzero(local_core))
        if core_count <= 0:
            return None
        if int(np.count_nonzero(local_object & local_core)) / core_count < 0.995:
            return None

        satellite = np.zeros((height, width), dtype=bool)
        satellite[:, region_x0:region_x1] = local_object
        ys, xs = np.where(satellite)
        if xs.size == 0:
            return None
        center_x = float(xs.mean() / width)
        if candidate.side == "left" and center_x > 0.44:
            return None
        if candidate.side == "right" and center_x < 0.56:
            return None

        visible = alpha > 0
        visible_count = int(np.count_nonzero(visible))
        satellite_count = int(np.count_nonzero(satellite & visible))
        if visible_count <= 0:
            return None
        share = satellite_count / visible_count
        if not (0.07 <= share <= 0.38):
            return None
        return satellite