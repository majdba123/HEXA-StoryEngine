from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from app.models import VisualAsset
from app.refinement2.models import CandidateProposal, ProposalSource
from app.refinement2.semantic import SemanticDetection, SemanticProposalBackend
from app.refinement2.segmenter import MaskBackend
from app.refinement2.extractor import Pass1StyleExtractor
from app.refinement2.proposal import CVProposalEngine
from app.refinement2.safety import PartitionSafetyGate
from app.refinement2.validator import DetachedObjectValidator
from app.shared.errors import StageFailedError


class Pass2RefinementService:
    """Detached-object recovery layer built around strict geometry preservation."""

    _MAX_SECONDARIES = 3

    def __init__(
        self,
        *,
        semantic_backend: SemanticProposalBackend | None = None,
        mask_backend: MaskBackend | None = None,
    ) -> None:
        self.proposals = CVProposalEngine()
        self.validator = DetachedObjectValidator()
        self.extractor = Pass1StyleExtractor()
        self.safety = PartitionSafetyGate()
        self.semantic_backend = semantic_backend
        self.mask_backend = mask_backend

    def refine(
        self,
        assets: list[VisualAsset],
        workspace: Path,
        scene_unit_types: dict[str, list[str]] | None = None,
    ) -> list[VisualAsset]:
        output_dir = workspace / "refinement2"
        output_dir.mkdir(parents=True, exist_ok=True)

        by_scene: dict[str, list[VisualAsset]] = {}
        order: list[str] = []
        for asset in assets:
            if asset.scene_id not in by_scene:
                by_scene[asset.scene_id] = []
                order.append(asset.scene_id)
            by_scene[asset.scene_id].append(asset)

        output: list[VisualAsset] = []
        for scene_id in order:
            rows = by_scene[scene_id]
            unit_types = (scene_unit_types or {}).get(scene_id, [])
            expected = len(unit_types) if unit_types else None
            # If authoring metadata says Pass 1 already has enough independent units,
            # Pass 2 must not invent more. This is generic package intent, not scene hacks.
            if expected is not None and len(rows) >= expected:
                output.extend(rows)
                continue
            missing = max(1, (expected - len(rows)) if expected is not None else 1)
            target_types = unit_types[len(rows):] if expected is not None else []

            ranked = sorted(
                enumerate(rows),
                key=lambda row: row[1].source_area_ratio or 0.0,
                reverse=True,
            )
            replacements: dict[int, list[VisualAsset]] = {}
            remaining = missing
            for index, asset in ranked:
                if remaining <= 0:
                    break
                derived = self._refine_asset(
                    asset,
                    output_dir,
                    max_secondaries=remaining,
                    target_types=target_types,
                )
                if derived is None:
                    continue
                additions = len(derived) - 1
                if additions <= 0:
                    continue
                replacements[index] = derived
                remaining -= additions
            for index, asset in enumerate(rows):
                output.extend(replacements.get(index, [asset]))
        return output

    def _refine_asset(
        self,
        asset: VisualAsset,
        output_dir: Path,
        *,
        max_secondaries: int = 1,
        target_types: list[str] | None = None,
    ) -> list[VisualAsset] | None:
        if not asset.image_path.is_file():
            raise StageFailedError(
                "refinement2 input asset is missing",
                details={"asset_id": asset.id, "path": str(asset.image_path)},
            )
        with Image.open(asset.image_path) as opened:
            rgba = np.asarray(opened.convert("RGBA"))
        proposals = self.proposals.propose(rgba)
        if not proposals:
            return None

        dominant = max(proposals, key=lambda row: row.area_share)
        candidates = [row for row in proposals if row.id != dominant.id]
        candidates.sort(
            key=lambda row: self._candidate_priority(row, rgba.shape[:2], target_types or []),
            reverse=True,
        )
        accepted_masks: list[np.ndarray] = []
        for candidate in candidates:
            if not self._candidate_allowed_for_target(candidate, rgba.shape[:2], target_types or []):
                continue
            decision = self.validator.validate(rgba, candidate, dominant)
            if not decision.accepted:
                continue
            protected = dominant.core_mask.copy()
            for other in proposals:
                if other.id not in {candidate.id, dominant.id}:
                    protected |= other.core_mask
            roi_bounds = self._safe_roi(candidate, proposals, rgba.shape[1], rgba.shape[0])
            extracted = self.extractor.extract(
                rgba,
                candidate,
                protected,
                roi_bounds=roi_bounds,
            )
            if extracted is None:
                continue
            if any(np.any(mask & extracted.mask) for mask in accepted_masks):
                continue
            accepted_masks.append(extracted.mask)
            if len(accepted_masks) >= min(self._MAX_SECONDARIES, max_secondaries):
                break

        remaining_slots = min(self._MAX_SECONDARIES, max_secondaries) - len(accepted_masks)
        if remaining_slots > 0 and self.semantic_backend is not None and self.mask_backend is not None:
            semantic_masks = self._semantic_recovery(
                asset=asset,
                rgba=rgba,
                dominant=dominant,
                target_types=target_types or [],
                limit=remaining_slots,
                existing=accepted_masks,
            )
            accepted_masks.extend(semantic_masks)

        if not self.safety.validate(rgba[:, :, 3], accepted_masks):
            return None
        return self._emit(asset, rgba, accepted_masks, output_dir)

    def _semantic_recovery(
        self,
        *,
        asset: VisualAsset,
        rgba: np.ndarray,
        dominant: CandidateProposal,
        target_types: list[str],
        limit: int,
        existing: list[np.ndarray],
    ) -> list[np.ndarray]:
        try:
            detections = self.semantic_backend.detect(asset.image_path) if self.semantic_backend else []
        except Exception:
            return []
        if not detections:
            return []
        detections = sorted(
            detections,
            key=lambda row: self._semantic_priority(row, rgba.shape[:2], target_types),
            reverse=True,
        )
        alpha = rgba[:, :, 3]
        rgb = rgba[:, :, :3]
        hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
        visible_count = max(1, int(np.count_nonzero(alpha > 0)))
        output: list[np.ndarray] = []
        for index, detection in enumerate(detections):
            if len(output) >= limit:
                break
            if self._semantic_priority(detection, rgba.shape[:2], target_types) <= 0:
                continue
            mask = self.mask_backend.segment(asset.image_path, detection.bbox) if self.mask_backend else None
            if mask is None or mask.shape != alpha.shape:
                continue
            mask = np.asarray(mask, dtype=bool) & (alpha > 0)
            if not np.any(mask):
                continue
            if any(self._mask_iou(mask, prior) >= 0.35 for prior in [*existing, *output]):
                continue

            hard_core = (
                mask
                & (alpha >= 24)
                & (((hsv[:, :, 1] >= 18) & (hsv[:, :, 2] <= 250)) | (hsv[:, :, 2] <= 205))
            )
            ys, xs = np.where(hard_core)
            if xs.size == 0:
                continue
            x0, y0, x1, y1 = int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1
            candidate = CandidateProposal(
                id=f"semantic-{index + 1:02d}",
                bbox=(x0, y0, x1 - x0, y1 - y0),
                center=(float(xs.mean()), float(ys.mean())),
                area_share=float(np.count_nonzero(mask)) / visible_count,
                stability=1.0,
                source=ProposalSource.semantic,
                core_mask=hard_core,
            )
            if not self._candidate_allowed_for_target(candidate, rgba.shape[:2], target_types):
                continue
            decision = self.validator.validate(rgba, candidate, dominant)
            if not decision.accepted:
                continue
            leak = int(np.count_nonzero(mask & dominant.core_mask)) / max(1, int(np.count_nonzero(mask)))
            share = int(np.count_nonzero(mask)) / visible_count
            if leak > 0.005 or not (0.025 <= share <= 0.48):
                continue
            output.append(mask)
        return output

    @staticmethod
    def _semantic_priority(
        detection: SemanticDetection,
        shape: tuple[int, int],
        target_types: list[str],
    ) -> float:
        height, width = shape
        label = detection.label.lower()
        x, y, bw, bh = detection.bbox
        if bw <= 0 or bh <= 0 or x >= width or y >= height:
            return -1.0
        score = float(detection.confidence)
        wants_character = any(
            token in str(unit_type).upper()
            for unit_type in target_types
            for token in ("CHARACTER", "PERSON", "HUMAN")
        )
        if wants_character:
            semantic_match = any(token in label for token in ("person", "human", "character", "man", "woman", "boy", "girl", "people"))
            if semantic_match:
                score += 4.0
            aspect = bh / max(1, bw)
            score += min(2.5, aspect) * 0.7 + (bh / max(1, height)) * 1.5
        return score

    @staticmethod
    def _mask_iou(a: np.ndarray, b: np.ndarray) -> float:
        inter = int(np.count_nonzero(a & b))
        union = int(np.count_nonzero(a | b))
        return inter / union if union > 0 else 0.0

    @staticmethod
    def _candidate_allowed_for_target(candidate, shape: tuple[int, int], target_types: list[str]) -> bool:
        wants_character = any(
            token in str(unit_type).upper()
            for unit_type in target_types
            for token in ("CHARACTER", "PERSON", "HUMAN")
        )
        if not wants_character:
            return True
        height, width = shape
        _x, _y, bw, bh = candidate.bbox
        # CV-only character recovery is deliberately strict. A partial torso/legs mask
        # is worse than a missed split; semantic/SAM backends can later recover smaller
        # complete figures safely.
        height_share = bh / max(1, height)
        width_share = bw / max(1, width)
        aspect = bh / max(1, bw)
        return (
            height_share >= 0.68
            and 0.08 <= width_share <= 0.42
            and aspect >= 1.20
        )

    @staticmethod
    def _candidate_priority(candidate, shape: tuple[int, int], target_types: list[str]) -> float:
        height, width = shape
        x, y, bw, bh = candidate.bbox
        score = candidate.stability * 2.0 + candidate.area_share
        wants_character = any(
            token in str(unit_type).upper()
            for unit_type in target_types
            for token in ("CHARACTER", "PERSON", "HUMAN")
        )
        if wants_character:
            aspect = bh / max(1, bw)
            height_share = bh / max(1, height)
            width_share = bw / max(1, width)
            figure_score = (
                min(2.5, aspect) * 0.8
                + min(1.0, height_share) * 1.8
                - max(0.0, width_share - 0.42) * 2.0
            )
            score += figure_score * 3.0
        return score

    @staticmethod
    def _safe_roi(
        candidate,
        proposals,
        width: int,
        height: int,
    ) -> tuple[int, int, int, int]:
        """Bound internal extraction by real proposal gaps without changing output geometry."""
        cx, cy, cw, ch = candidate.bbox
        cx2, cy2 = cx + cw, cy + ch
        left, top, right, bottom = 0, 0, width, height
        for other in proposals:
            if other.id == candidate.id:
                continue
            ox, oy, ow, oh = other.bbox
            ox2, oy2 = ox + ow, oy + oh
            vertical_overlap = max(0, min(cy2, oy2) - max(cy, oy))
            horizontal_overlap = max(0, min(cx2, ox2) - max(cx, ox))
            vertical_ratio = vertical_overlap / max(1, min(ch, oh))
            horizontal_ratio = horizontal_overlap / max(1, min(cw, ow))
            if vertical_ratio >= 0.20:
                if ox2 <= cx:
                    left = max(left, (ox2 + cx) // 2)
                elif ox >= cx2:
                    right = min(right, (cx2 + ox) // 2)
            if horizontal_ratio >= 0.20:
                if oy2 <= cy:
                    top = max(top, (oy2 + cy) // 2)
                elif oy >= cy2:
                    bottom = min(bottom, (cy2 + oy) // 2)
        # Candidate bbox must always remain fully inside the analysis ROI.
        left = min(left, cx)
        top = min(top, cy)
        right = max(right, cx2)
        bottom = max(bottom, cy2)
        return max(0, left), max(0, top), min(width, right), min(height, bottom)

    def _emit(
        self,
        asset: VisualAsset,
        rgba: np.ndarray,
        secondary_masks: list[np.ndarray],
        output_dir: Path,
    ) -> list[VisualAsset]:
        alpha = rgba[:, :, 3]
        union = np.zeros(alpha.shape, dtype=bool)
        for mask in secondary_masks:
            union |= mask

        safe_name = asset.id.replace(":", "-").replace("/", "-")
        main_rgba = rgba.copy()
        main_rgba[:, :, 3] = np.where(union, 0, alpha).astype(np.uint8)
        main_path = output_dir / f"{safe_name}-main.png"
        Image.fromarray(main_rgba, mode="RGBA").save(main_path, format="PNG", compress_level=3)

        visible_count = max(1, int(np.count_nonzero(alpha > 0)))
        parent_ratio = asset.source_area_ratio or 0.0
        total_secondary_share = int(np.count_nonzero(union)) / visible_count
        output: list[VisualAsset] = [asset.model_copy(update={
            "image_path": main_path,
            "source_area_ratio": parent_ratio * (1.0 - total_secondary_share),
            "extraction_method": f"{asset.extraction_method}+pass2_main",
            # geometry intentionally unchanged: source_bbox/canvas copied verbatim
        })]

        for index, mask in enumerate(secondary_masks, start=1):
            secondary_rgba = rgba.copy()
            secondary_rgba[:, :, 3] = np.where(mask, alpha, 0).astype(np.uint8)
            secondary_path = output_dir / f"{safe_name}-secondary-{index:02d}.png"
            Image.fromarray(secondary_rgba, mode="RGBA").save(
                secondary_path,
                format="PNG",
                compress_level=3,
            )
            share = int(np.count_nonzero(mask)) / visible_count
            output.append(asset.model_copy(update={
                "id": f"{asset.id}:secondary-{index:02d}",
                "role": "secondary_object",
                "image_path": secondary_path,
                "source_area_ratio": parent_ratio * share,
                "confidence": min(asset.confidence, 0.95),
                "extraction_method": f"{asset.extraction_method}+pass2_secondary",
                "independent": True,
                "compound": False,
                "component_count": 1,
                "can_animate_independently": True,
                # source_bbox/source_canvas deliberately inherited exactly
            }))
        return output
