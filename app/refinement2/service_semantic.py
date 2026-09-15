from __future__ import annotations

import cv2
import numpy as np

from app.models import VisualAsset
from app.refinement2.models import CandidateProposal, ProposalSource
from app.refinement2.semantic import SemanticDetection


class _SemanticRecoveryMixin:
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
