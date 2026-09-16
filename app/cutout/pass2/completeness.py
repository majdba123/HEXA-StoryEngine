from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass(frozen=True, slots=True)
class CompletionResult:
    mask: np.ndarray
    added_pixels: int
    unresolved_pixels: int
    ambiguous: bool


class WholeObjectCompleter:
    """Complete a detached-object mask without stealing pixels from its parent.

    Pass2 proposals are intentionally driven by strong structural ink. Authored objects
    often have visually-bound pieces that are weaker or disconnected from that ink:
    alarm rays, clock hands/dots, highlights, anti-aliased edges and soft shadows. If
    those pieces remain on the parent layer they appear as a ghost before the detached
    object enters.

    Completion is spatial/ownership based rather than scene-specific:
    * work only inside a conservative envelope around the accepted seed;
    * label *residual* alpha after removing the seed and protected parent/peer cores;
    * absorb enclosed islands and small nearby satellites only when they are closer to
      the seed than to protected structure;
    * absorb a narrow ownership halo for antialiasing/soft shadows;
    * reject a split when a material nearby region remains ambiguous.

    The output always keeps the original full canvas. No crop, resize or nearest-pixel
    repartition is performed.
    """

    _MIN_ALPHA = 3
    _MAX_ENCLOSED_RATIO = 0.55
    _MAX_SATELLITE_RATIO = 0.30
    _MAX_UNRESOLVED_RATIO = 0.060

    def complete(
        self,
        rgba: np.ndarray,
        seed_mask: np.ndarray,
        protected: np.ndarray | None = None,
    ) -> CompletionResult | None:
        alpha = rgba[:, :, 3]
        visible = alpha >= self._MIN_ALPHA
        seed = np.asarray(seed_mask, dtype=bool) & visible
        if not np.any(seed):
            return None

        protected_mask = (
            np.asarray(protected, dtype=bool) & visible
            if protected is not None
            else np.zeros_like(seed, dtype=bool)
        )
        protected_mask &= ~seed

        completed = seed.copy()
        original_count = int(np.count_nonzero(completed))
        for _ in range(3):
            expanded = self._absorb_components(visible, completed, protected_mask)
            expanded = self._absorb_soft_ownership(visible, expanded, protected_mask)
            if np.array_equal(expanded, completed):
                break
            completed = expanded

        completed &= visible
        completed &= ~protected_mask
        if not np.any(completed):
            return None

        unresolved, ambiguous = self._unresolved_associated_pixels(
            visible=visible,
            completed=completed,
            protected=protected_mask,
        )
        completed_count = max(1, int(np.count_nonzero(completed)))
        unresolved_count = int(np.count_nonzero(unresolved))
        if ambiguous or unresolved_count / completed_count > self._MAX_UNRESOLVED_RATIO:
            return None

        return CompletionResult(
            mask=completed,
            added_pixels=max(0, completed_count - original_count),
            unresolved_pixels=unresolved_count,
            ambiguous=False,
        )

    def _absorb_components(
        self,
        visible: np.ndarray,
        completed: np.ndarray,
        protected: np.ndarray,
    ) -> np.ndarray:
        out = completed.copy()
        x0, y0, x1, y1 = self._bounds(completed)
        width = max(1, x1 - x0)
        height = max(1, y1 - y0)
        seed_area = max(1, int(np.count_nonzero(completed)))

        # The envelope must be large enough for authored callout rays/shadows, while
        # remaining local enough that a small icon cannot absorb a neighboring object.
        ex = max(10, min(72, round(width * 0.34)))
        ey = max(10, min(72, round(height * 0.34)))
        near_gap = max(6.0, min(46.0, min(width, height) * 0.22))
        h, w = visible.shape
        envelope = np.zeros_like(visible, dtype=bool)
        envelope[
            max(0, y0 - ey): min(h, y1 + ey),
            max(0, x0 - ex): min(w, x1 + ex),
        ] = True

        residual = visible & envelope & ~completed & ~protected
        if not np.any(residual):
            return out

        candidate_distance = self._distance_to(completed)
        protected_distance = self._distance_to(protected) if np.any(protected) else None
        count, labels, stats, centers = cv2.connectedComponentsWithStats(
            residual.astype(np.uint8), connectivity=8
        )
        for label in range(1, count):
            component = labels == label
            component_area = int(stats[label, cv2.CC_STAT_AREA])
            if component_area <= 0:
                continue

            bx = int(stats[label, cv2.CC_STAT_LEFT])
            by = int(stats[label, cv2.CC_STAT_TOP])
            bw = int(stats[label, cv2.CC_STAT_WIDTH])
            bh = int(stats[label, cv2.CC_STAT_HEIGHT])
            cx, cy = float(centers[label][0]), float(centers[label][1])
            seed_dist = float(candidate_distance[component].min())
            protected_dist = (
                float(protected_distance[component].min())
                if protected_distance is not None
                else float("inf")
            )
            ratio = component_area / seed_area

            # A piece whose centroid sits inside the seed silhouette envelope is a
            # strong whole-object signal (clock hands/dots inside an outer ring).
            inside_seed_bbox = x0 <= cx <= x1 and y0 <= cy <= y1
            enclosed_piece = inside_seed_bbox and ratio <= self._MAX_ENCLOSED_RATIO

            # Exterior decorative pieces (alarm rays, spark/glow islands) must be small,
            # close to the seed, and geometrically local to its box.
            satellite = (
                seed_dist <= near_gap
                and ratio <= self._MAX_SATELLITE_RATIO
                and self._bbox_near(
                    (bx, by, bw, bh),
                    (x0, y0, x1 - x0, y1 - y0),
                    near_gap,
                )
            )

            # Do not steal parent-owned material. A small margin avoids ties at shared
            # anti-aliased boundaries while still permitting detached weak decorations.
            owned_by_seed = seed_dist + 1.5 < protected_dist or protected_dist > near_gap * 1.8
            if (enclosed_piece or satellite) and owned_by_seed:
                out |= component
        return out

    def _absorb_soft_ownership(
        self,
        visible: np.ndarray,
        completed: np.ndarray,
        protected: np.ndarray,
    ) -> np.ndarray:
        x0, y0, x1, y1 = self._bounds(completed)
        width = max(1, x1 - x0)
        height = max(1, y1 - y0)
        radius = max(3, min(14, round(min(width, height) * 0.04)))
        kernel = cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE,
            (radius * 2 + 1, radius * 2 + 1),
        )
        zone = cv2.dilate(completed.astype(np.uint8), kernel, iterations=1) > 0
        candidate_distance = self._distance_to(completed)
        if np.any(protected):
            protected_distance = self._distance_to(protected)
            ownership = candidate_distance + 1.0 < protected_distance
        else:
            ownership = np.ones_like(completed, dtype=bool)
        soft = visible & zone & ownership & ~protected
        return completed | soft

    def _unresolved_associated_pixels(
        self,
        *,
        visible: np.ndarray,
        completed: np.ndarray,
        protected: np.ndarray,
    ) -> tuple[np.ndarray, bool]:
        x0, y0, x1, y1 = self._bounds(completed)
        width = max(1, x1 - x0)
        height = max(1, y1 - y0)
        radius = max(7, min(34, round(min(width, height) * 0.15)))
        kernel = cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE,
            (radius * 2 + 1, radius * 2 + 1),
        )
        zone = cv2.dilate(completed.astype(np.uint8), kernel, iterations=1) > 0
        residual = visible & zone & ~completed & ~protected
        if not np.any(residual):
            return residual, False

        candidate_distance = self._distance_to(completed)
        protected_distance = self._distance_to(protected) if np.any(protected) else None
        close = residual & (candidate_distance <= radius)
        if protected_distance is None:
            return close, False

        seed_owned = close & (candidate_distance + 2.0 < protected_distance)
        ambiguous_zone = close & (np.abs(candidate_distance - protected_distance) <= 2.0)
        ambiguous = int(np.count_nonzero(ambiguous_zone)) > max(
            64,
            round(np.count_nonzero(completed) * 0.015),
        )
        return seed_owned, ambiguous

    @staticmethod
    def _distance_to(mask: np.ndarray) -> np.ndarray:
        inverse = np.where(mask, 0, 255).astype(np.uint8)
        return cv2.distanceTransform(inverse, cv2.DIST_L2, 5)

    @staticmethod
    def _bounds(mask: np.ndarray) -> tuple[int, int, int, int]:
        ys, xs = np.where(mask)
        return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1

    @staticmethod
    def _bbox_near(
        left: tuple[int, int, int, int],
        right: tuple[int, int, int, int],
        gap: float,
    ) -> bool:
        lx, ly, lw, lh = left
        rx, ry, rw, rh = right
        lcx, lcy = lx + lw / 2, ly + lh / 2
        rcx, rcy = rx + rw / 2, ry + rh / 2
        return (
            abs(lcx - rcx) <= (lw + rw) / 2 + gap
            and abs(lcy - rcy) <= (lh + rh) / 2 + gap
        )
