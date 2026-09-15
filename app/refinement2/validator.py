from __future__ import annotations

import cv2
import numpy as np

from app.refinement2.models import CandidateProposal, DetachedDecision


class DetachedObjectValidator:
    """Fail-closed validator for detached-only recovery."""

    _MIN_STABILITY = 2 / 3
    # Slightly relaxed to admit clearly detached objects with very tight gutters.
    _MIN_NORMALIZED_GAP = 0.0024
    _MAX_TOUCH_SCORE = 0.02

    def validate(
        self,
        rgba: np.ndarray,
        candidate: CandidateProposal,
        dominant: CandidateProposal,
    ) -> DetachedDecision:
        if candidate.id == dominant.id:
            return DetachedDecision(False, 0.0, 1.0, candidate.stability, "dominant")
        if candidate.stability < self._MIN_STABILITY:
            return DetachedDecision(False, 0.0, 1.0, candidate.stability, "unstable")

        h, w = rgba.shape[:2]
        alpha = rgba[:, :, 3]
        rgb = rgba[:, :, :3]
        hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)

        # Real-contact mask: keep dark/colored object ink, reject weak neutral shadows.
        contact = (
            (alpha >= 28)
            & ((hsv[:, :, 1] >= 18) | (hsv[:, :, 2] <= 212))
        ).astype(np.uint8)
        count, labels = cv2.connectedComponents(contact, connectivity=8)
        if count <= 1:
            return DetachedDecision(False, 0.0, 1.0, candidate.stability, "no structural components")

        candidate_labels = self._labels_under(labels, candidate.core_mask)
        dominant_labels = self._labels_under(labels, dominant.core_mask)
        if candidate_labels & dominant_labels:
            return DetachedDecision(False, 0.0, 1.0, candidate.stability, "hard contact")

        candidate_core = candidate.core_mask.astype(np.uint8)
        dominant_core = dominant.core_mask.astype(np.uint8)
        # Distance from candidate core to dominant core in pixels.
        inv = np.where(dominant_core > 0, 0, 255).astype(np.uint8)
        distance = cv2.distanceTransform(inv, cv2.DIST_L2, 5)
        values = distance[candidate_core > 0]
        if values.size == 0:
            return DetachedDecision(False, 0.0, 1.0, candidate.stability, "empty candidate")
        min_gap = float(values.min())
        normalized_gap = min_gap / max(1.0, (h * h + w * w) ** 0.5)

        # Touch score: dilation collision at a tiny radius. Detached objects may be close,
        # but they should not share hard ink.
        radius = max(1, round(min(h, w) * 0.003))
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (radius * 2 + 1, radius * 2 + 1))
        dilated = cv2.dilate(candidate_core, kernel, iterations=1) > 0
        dominant_bool = dominant_core > 0
        touch_pixels = int(np.count_nonzero(dilated & dominant_bool))
        candidate_pixels = max(1, int(np.count_nonzero(candidate_core)))
        touch_score = touch_pixels / candidate_pixels

        accepted = normalized_gap >= self._MIN_NORMALIZED_GAP and touch_score <= self._MAX_TOUCH_SCORE
        reason = None if accepted else "insufficient real gap"
        return DetachedDecision(
            accepted=accepted,
            gutter_score=min(1.0, normalized_gap / 0.03),
            touch_score=touch_score,
            stability_score=candidate.stability,
            reason=reason,
        )

    @staticmethod
    def _labels_under(labels: np.ndarray, mask: np.ndarray) -> set[int]:
        values = labels[mask]
        return {int(value) for value in np.unique(values) if int(value) > 0}
