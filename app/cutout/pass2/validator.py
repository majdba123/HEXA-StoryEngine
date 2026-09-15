from __future__ import annotations

import cv2
import numpy as np

from app.cutout.pass2.models import CandidateProposal, DetachedDecision


class DetachedObjectValidator:
    """Fail-closed validator for *externally detached* object recovery.

    The key distinction is topological rather than semantic: a candidate may be a
    meaningful icon/person/card, but Pass 2 accepts it only when its surrounding free
    space is connected to the exterior of the parent canvas. This rejects decorations
    enclosed inside a phone/card/calendar while preserving genuinely detached objects,
    even when their visual gap is small.
    """

    _MIN_STABILITY = 3 / 7
    _MIN_NORMALIZED_GAP = 0.0015
    _MAX_TOUCH_SCORE = 0.02
    _MIN_EXTERIOR_MOAT_RATIO = 0.84

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

        # Strong visual ink. Weak neutral shadows are intentionally excluded so a
        # detached object is not fused back into the parent by a soft ground shadow.
        contact = (
            (alpha >= 28)
            & ((hsv[:, :, 1] >= 18) | (hsv[:, :, 2] <= 212))
        ).astype(np.uint8)
        count, labels = cv2.connectedComponents(contact, connectivity=8)
        if count <= 1:
            return DetachedDecision(False, 0.0, 1.0, candidate.stability, "no structural components")

        candidate_labels = self._labels_under(labels, candidate.core_mask)
        dominant_labels = self._labels_under(labels, dominant.core_mask)
        hard_shared = bool(candidate_labels & dominant_labels)

        candidate_core = candidate.core_mask.astype(np.uint8)
        dominant_core = dominant.core_mask.astype(np.uint8)
        candidate_bool = candidate_core > 0
        dominant_bool = dominant_core > 0

        # Distance to the dominant hard core. This remains a conservative minimum-gap
        # gate, but is deliberately small; topology below decides whether the candidate
        # is actually outside the parent cluster.
        inv = np.where(dominant_bool, 0, 255).astype(np.uint8)
        distance = cv2.distanceTransform(inv, cv2.DIST_L2, 5)
        values = distance[candidate_bool]
        if values.size == 0:
            return DetachedDecision(False, 0.0, 1.0, candidate.stability, "empty candidate")
        min_gap = float(values.min())
        normalized_gap = min_gap / max(1.0, (h * h + w * w) ** 0.5)

        radius = max(1, round(min(h, w) * 0.003))
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (radius * 2 + 1, radius * 2 + 1))
        dilated = cv2.dilate(candidate_core, kernel, iterations=1) > 0
        touch_pixels = int(np.count_nonzero(dilated & dominant_bool))
        candidate_pixels = max(1, int(np.count_nonzero(candidate_bool)))
        touch_score = touch_pixels / candidate_pixels

        exterior_moat_ratio = self._exterior_moat_ratio(
            contact=contact,
            labels=labels,
            candidate_labels=candidate_labels,
            candidate_core=candidate_core,
        )

        # A shared hard component normally means physical attachment. A narrow visual
        # connector may still exist for a large external figure/callout; those are not
        # accepted here by default. The service can use the conservative hard-core
        # fallback only when additional whole-object geometry gates pass.
        accepted = (
            not hard_shared
            and normalized_gap >= self._MIN_NORMALIZED_GAP
            and touch_score <= self._MAX_TOUCH_SCORE
            and exterior_moat_ratio >= self._MIN_EXTERIOR_MOAT_RATIO
        )
        if accepted:
            reason = None
        elif hard_shared:
            reason = "hard contact"
        elif exterior_moat_ratio < self._MIN_EXTERIOR_MOAT_RATIO:
            reason = "enclosed or fused subpart"
        else:
            reason = "insufficient real gap"

        return DetachedDecision(
            accepted=accepted,
            gutter_score=exterior_moat_ratio,
            touch_score=touch_score,
            stability_score=candidate.stability,
            reason=reason,
        )

    def external_moat_score(
        self,
        rgba: np.ndarray,
        candidate: CandidateProposal,
    ) -> float:
        """Public diagnostic used by the fallback extractor gate."""
        alpha = rgba[:, :, 3]
        hsv = cv2.cvtColor(rgba[:, :, :3], cv2.COLOR_RGB2HSV)
        contact = (
            (alpha >= 28)
            & ((hsv[:, :, 1] >= 18) | (hsv[:, :, 2] <= 212))
        ).astype(np.uint8)
        _, labels = cv2.connectedComponents(contact, connectivity=8)
        candidate_labels = self._labels_under(labels, candidate.core_mask)
        return self._exterior_moat_ratio(
            contact=contact,
            labels=labels,
            candidate_labels=candidate_labels,
            candidate_core=candidate.core_mask.astype(np.uint8),
        )

    @staticmethod
    def _exterior_moat_ratio(
        *,
        contact: np.ndarray,
        labels: np.ndarray,
        candidate_labels: set[int],
        candidate_core: np.ndarray,
    ) -> float:
        h, w = contact.shape
        # Remove the candidate itself from the barrier. The remaining hard structure
        # defines enclosed vs exterior free space.
        other_barrier = contact.astype(bool)
        for label in candidate_labels:
            other_barrier[labels == label] = False

        padded = np.pad(other_barrier, 1, mode="constant", constant_values=False)
        free = (~padded).astype(np.uint8) * 255
        flood_mask = np.zeros((free.shape[0] + 2, free.shape[1] + 2), dtype=np.uint8)
        cv2.floodFill(free, flood_mask, (0, 0), 128)
        exterior = (free == 128)[1:-1, 1:-1]

        radius = max(3, round(min(h, w) * 0.010))
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (radius * 2 + 1, radius * 2 + 1))
        candidate_bool = candidate_core > 0
        outer = cv2.dilate(candidate_core, kernel, iterations=1) > 0
        ring = outer & ~candidate_bool
        ring_pixels = max(1, int(np.count_nonzero(ring)))
        exterior_ring = ring & ~other_barrier & exterior
        return int(np.count_nonzero(exterior_ring)) / ring_pixels

    @staticmethod
    def _labels_under(labels: np.ndarray, mask: np.ndarray) -> set[int]:
        values = labels[mask]
        return {int(value) for value in np.unique(values) if int(value) > 0}
