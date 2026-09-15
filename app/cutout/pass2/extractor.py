from __future__ import annotations

import cv2
import numpy as np

from app.cutout.pass2.models import CandidateProposal, ExtractionResult


class Pass1StyleExtractor:
    """Recover a whole object on the parent canvas using Pass-1-style flood fill.

    This never crops, resizes, or repositions output geometry. A local ROI is used only
    as an internal flood-fill workspace; the returned mask is always parent-canvas sized.
    """

    _MIN_ALPHA_SHARE = 0.010
    _MAX_ALPHA_SHARE = 0.50

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
        margin = max(10, round(max(bw, bh) * 0.10))
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
        if not np.any(roi_core):
            return None

        hsv = cv2.cvtColor(roi_rgb, cv2.COLOR_RGB2HSV)
        structural = (
            (roi_alpha >= 16)
            & ((hsv[:, :, 1] >= 20) | (hsv[:, :, 2] <= 236))
        )
        count, labels = cv2.connectedComponents(structural.astype(np.uint8), connectivity=8)
        keep_labels: set[int] = set()
        for label in range(1, count):
            component = labels == label
            if np.any(component & roi_core):
                keep_labels.add(label)
        if not keep_labels:
            return None
        barrier = np.isin(labels, list(keep_labels))

        full = self._silhouette_from_barrier(
            barrier=barrier,
            alpha=alpha,
            roi_alpha=roi_alpha,
            x0=x0,
            y0=y0,
            x1=x1,
            y1=y1,
        )
        return self._result(rgba, candidate, protected_cores, full)

    def extract_hard_core(
        self,
        rgba: np.ndarray,
        candidate: CandidateProposal,
        protected_cores: np.ndarray,
    ) -> ExtractionResult | None:
        """Fallback for externally detached objects bridged by weak structural pixels.

        Only hard/contact components already under the validated candidate are used as
        a barrier. No ownership/Voronoi/GrabCut repartition is performed. The output
        remains a full parent-canvas mask and must pass the same exact safety gates.
        """
        h, w = rgba.shape[:2]
        alpha = rgba[:, :, 3]
        hsv = cv2.cvtColor(rgba[:, :, :3], cv2.COLOR_RGB2HSV)
        contact = (
            (alpha >= 28)
            & ((hsv[:, :, 1] >= 18) | (hsv[:, :, 2] <= 212))
        ).astype(np.uint8)
        _, labels = cv2.connectedComponents(contact, connectivity=8)
        candidate_labels = {
            int(value)
            for value in np.unique(labels[candidate.core_mask])
            if int(value) > 0
        }
        if not candidate_labels:
            return None

        selected = np.isin(labels, list(candidate_labels))
        shared_with_protected = bool(np.any(selected & protected_cores))
        # If a thin hard connector joined candidate and parent, never inherit the full
        # connected component; use the stable candidate core only.
        barrier_full = candidate.core_mask.copy() if shared_with_protected else (selected | candidate.core_mask)
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        barrier_full = cv2.morphologyEx(
            barrier_full.astype(np.uint8) * 255,
            cv2.MORPH_CLOSE,
            kernel,
            iterations=1,
        ) > 0

        x, y, bw, bh = candidate.bbox
        # Generous analysis padding prevents a white/light object interior from being
        # opened to the flood-fill boundary when the structural bbox misses its soft edge.
        margin = max(16, round(max(bw, bh) * 0.15))
        x0, y0 = max(0, x - margin), max(0, y - margin)
        x1, y1 = min(w, x + bw + margin), min(h, y + bh + margin)
        if x1 - x0 < 4 or y1 - y0 < 4:
            return None

        barrier = barrier_full[y0:y1, x0:x1]
        roi_alpha = alpha[y0:y1, x0:x1]
        full = self._silhouette_from_barrier(
            barrier=barrier,
            alpha=alpha,
            roi_alpha=roi_alpha,
            x0=x0,
            y0=y0,
            x1=x1,
            y1=y1,
        )
        return self._result(rgba, candidate, protected_cores, full)

    @staticmethod
    def _silhouette_from_barrier(
        *,
        barrier: np.ndarray,
        alpha: np.ndarray,
        roi_alpha: np.ndarray,
        x0: int,
        y0: int,
        x1: int,
        y1: int,
    ) -> np.ndarray:
        padded = np.pad(barrier, 1, mode="constant", constant_values=False)
        open_space = (~padded).astype(np.uint8) * 255
        flood_mask = np.zeros((open_space.shape[0] + 2, open_space.shape[1] + 2), dtype=np.uint8)
        cv2.floodFill(open_space, flood_mask, (0, 0), 128)
        outside = open_space == 128
        silhouette = ~outside[1:-1, 1:-1]
        silhouette &= roi_alpha > 0

        full = np.zeros(alpha.shape, dtype=bool)
        full[y0:y1, x0:x1] = silhouette
        full &= alpha > 0
        return full

    def _result(
        self,
        rgba: np.ndarray,
        candidate: CandidateProposal,
        protected_cores: np.ndarray,
        full: np.ndarray,
    ) -> ExtractionResult | None:
        alpha = rgba[:, :, 3]
        seed_count = max(1, int(np.count_nonzero(candidate.core_mask)))
        seed_coverage = int(np.count_nonzero(full & candidate.core_mask)) / seed_count
        extracted_count = max(1, int(np.count_nonzero(full)))
        foreign_core_leak = int(np.count_nonzero(full & protected_cores)) / extracted_count
        visible_count = max(1, int(np.count_nonzero(alpha > 0)))
        alpha_share = int(np.count_nonzero(full)) / visible_count

        if seed_coverage < 0.985 or foreign_core_leak > 0.005:
            return None
        if not (self._MIN_ALPHA_SHARE <= alpha_share <= self._MAX_ALPHA_SHARE):
            return None
        return ExtractionResult(
            mask=full,
            seed_coverage=seed_coverage,
            foreign_core_leak=foreign_core_leak,
            alpha_share=alpha_share,
        )
