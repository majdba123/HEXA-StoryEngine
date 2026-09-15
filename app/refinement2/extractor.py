from __future__ import annotations

import cv2
import numpy as np

from app.refinement2.models import CandidateProposal, ExtractionResult


class Pass1StyleExtractor:
    """Recover a whole object on the parent canvas using Pass-1-style flood fill.

    This never crops, resizes, or repositions output geometry. A local ROI is used only
    as an internal flood-fill workspace; the returned mask is always parent-canvas sized.
    """

    def extract(
        self,
        rgba: np.ndarray,
        candidate: CandidateProposal,
        protected_cores: np.ndarray,
        roi_bounds: tuple[int, int, int, int] | None = None,
    ) -> ExtractionResult | None:
        h, w = rgba.shape[:2]
        alpha = rgba[:, :, 3]
        rgb = rgba[:, :, :3]
        x, y, bw, bh = candidate.bbox
        margin = max(8, round(max(bw, bh) * 0.08))
        x0, y0 = max(0, x - margin), max(0, y - margin)
        x1, y1 = min(w, x + bw + margin), min(h, y + bh + margin)
        if roi_bounds is not None:
            rx0, ry0, rx1, ry1 = roi_bounds
            x0 = max(x0, rx0)
            y0 = max(y0, ry0)
            x1 = min(x1, rx1)
            y1 = min(y1, ry1)
        if x1 - x0 < 4 or y1 - y0 < 4:
            return None

        roi_rgb = rgb[y0:y1, x0:x1]
        roi_alpha = alpha[y0:y1, x0:x1]
        roi_core = candidate.core_mask[y0:y1, x0:x1]
        roi_protected = protected_cores[y0:y1, x0:x1]
        if not np.any(roi_core):
            return None

        # Same core idea as Pass 1: target structural ink forms a barrier, then flood
        # from an outside padded border to recover enclosed white interiors.
        hsv = cv2.cvtColor(roi_rgb, cv2.COLOR_RGB2HSV)
        structural = (
            (roi_alpha >= 16)
            & ((hsv[:, :, 1] >= 20) | (hsv[:, :, 2] <= 236))
        )
        # Only retain structural components that intersect candidate seed.
        count, labels = cv2.connectedComponents(structural.astype(np.uint8), connectivity=8)
        keep_labels: set[int] = set()
        for label in range(1, count):
            component = labels == label
            if np.any(component & roi_core):
                keep_labels.add(label)
        if not keep_labels:
            return None
        barrier = np.isin(labels, list(keep_labels))

        padded = np.pad(barrier, 1, mode="constant", constant_values=False)
        open_space = (~padded).astype(np.uint8) * 255
        flood_mask = np.zeros((open_space.shape[0] + 2, open_space.shape[1] + 2), dtype=np.uint8)
        cv2.floodFill(open_space, flood_mask, (0, 0), 128)
        outside = open_space == 128
        silhouette = ~outside[1:-1, 1:-1]
        silhouette &= roi_alpha > 0

        full = np.zeros((h, w), dtype=bool)
        full[y0:y1, x0:x1] = silhouette
        full &= alpha > 0

        seed_count = max(1, int(np.count_nonzero(candidate.core_mask)))
        seed_coverage = int(np.count_nonzero(full & candidate.core_mask)) / seed_count
        extracted_count = max(1, int(np.count_nonzero(full)))
        foreign_core_leak = int(np.count_nonzero(full & protected_cores)) / extracted_count
        visible_count = max(1, int(np.count_nonzero(alpha > 0)))
        alpha_share = int(np.count_nonzero(full)) / visible_count

        if seed_coverage < 0.995 or foreign_core_leak > 0.005:
            return None
        if not (0.025 <= alpha_share <= 0.48):
            return None
        return ExtractionResult(
            mask=full,
            seed_coverage=seed_coverage,
            foreign_core_leak=foreign_core_leak,
            alpha_share=alpha_share,
        )
