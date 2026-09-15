from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

from app.cutout.pass2.models import CandidateProposal, ProposalSource


@dataclass(slots=True)
class _Cluster:
    members: list[tuple[int, np.ndarray, tuple[int, int, int, int], tuple[float, float], int]] = field(default_factory=list)

    @property
    def profiles(self) -> set[int]:
        return {row[0] for row in self.members}

    @property
    def bbox(self) -> tuple[int, int, int, int]:
        x0 = min(row[2][0] for row in self.members)
        y0 = min(row[2][1] for row in self.members)
        x1 = max(row[2][0] + row[2][2] for row in self.members)
        y1 = max(row[2][1] + row[2][3] for row in self.members)
        return (x0, y0, x1 - x0, y1 - y0)

    @property
    def center(self) -> tuple[float, float]:
        total = max(1, sum(row[4] for row in self.members))
        return (
            float(sum(row[3][0] * row[4] for row in self.members) / total),
            float(sum(row[3][1] * row[4] for row in self.members) / total),
        )

    @property
    def mask(self) -> np.ndarray:
        out = np.zeros_like(self.members[0][1], dtype=bool)
        for _, mask, _, _, _ in self.members:
            out |= mask
        return out

    @property
    def area(self) -> int:
        return max(row[4] for row in self.members)


class CVProposalEngine:
    """Find detached-object candidates without changing geometry.

    Pass 2 must stay Pass-1-like: propose more *detached* islands, but never by
    cutting through a visually fused cluster. The engine therefore only increases
    *proposal recall*. Real acceptance remains fail-closed in the validator and
    extractor.
    """

    _PROFILES = (
        # Baseline Pass-1-like probes.
        (20, 198, 3),
        (22, 192, 3),
        (26, 182, 5),
        (30, 172, 7),
        # One slightly more sensitive probe to expose detached islands separated by
        # a very small real gutter.
        (16, 206, 3),
    )
    # Strict structural-contact profiles. These intentionally suppress weak neutral
    # shadows/glows harder than the generic probes so detached figures/cards/badges
    # can appear as independent hard-ink islands.
    _HARD_PROFILES = (
        (18, 212),
        (16, 205),
    )
    _MIN_CONSENSUS = 2
    _MIN_AREA_SHARE = 0.009
    _MAX_AREA_SHARE = 0.72
    _MIN_DIM_SHARE = 0.03

    def propose(self, rgba: np.ndarray) -> list[CandidateProposal]:
        h, w = rgba.shape[:2]
        alpha = rgba[:, :, 3]
        rgb = rgba[:, :, :3]
        hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
        clusters: list[_Cluster] = []
        total_visible = max(1, int(np.count_nonzero(alpha > 0)))
        diagonal = float((h * h + w * w) ** 0.5)

        for profile_index, (sat_min, dark_value_max, kernel_size) in enumerate(self._PROFILES):
            structural = (
                (alpha >= 20)
                & (
                    ((hsv[:, :, 1] >= sat_min) & (hsv[:, :, 2] <= 250))
                    | (hsv[:, :, 2] <= dark_value_max)
                )
            ).astype(np.uint8) * 255
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel_size, kernel_size))
            opened = cv2.morphologyEx(structural, cv2.MORPH_OPEN, kernel)
            self._collect_components(
                opened=opened,
                profile_index=profile_index,
                clusters=clusters,
                total_visible=total_visible,
                width=w,
                height=h,
                diagonal=diagonal,
            )

        profile_offset = len(self._PROFILES)
        for hard_index, (sat_min, dark_value_max) in enumerate(self._HARD_PROFILES):
            hard_contact = (
                (alpha >= 26)
                & ((hsv[:, :, 1] >= sat_min) | (hsv[:, :, 2] <= dark_value_max))
            ).astype(np.uint8) * 255
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
            cleaned = cv2.morphologyEx(hard_contact, cv2.MORPH_OPEN, kernel)
            self._collect_components(
                opened=cleaned,
                profile_index=profile_offset + hard_index,
                clusters=clusters,
                total_visible=total_visible,
                width=w,
                height=h,
                diagonal=diagonal,
            )

        total_profiles = len(self._PROFILES) + len(self._HARD_PROFILES)
        accepted = [cluster for cluster in clusters if len(cluster.profiles) >= self._MIN_CONSENSUS]
        accepted.sort(key=lambda row: row.area, reverse=True)
        proposals: list[CandidateProposal] = []
        for index, cluster in enumerate(accepted):
            proposals.append(CandidateProposal(
                id=f"cv-{index + 1:02d}",
                bbox=cluster.bbox,
                center=cluster.center,
                area_share=cluster.area / total_visible,
                stability=len(cluster.profiles) / total_profiles,
                source=ProposalSource.cv,
                core_mask=cluster.mask,
            ))
        return proposals

    def _collect_components(
        self,
        *,
        opened: np.ndarray,
        profile_index: int,
        clusters: list[_Cluster],
        total_visible: int,
        width: int,
        height: int,
        diagonal: float,
    ) -> None:
        count, labels, stats, centers = cv2.connectedComponentsWithStats(opened, connectivity=8)
        for label in range(1, count):
            x, y, bw, bh, area = [int(v) for v in stats[label]]
            if area <= 0:
                continue
            area_share = area / total_visible
            if not (self._MIN_AREA_SHARE <= area_share <= self._MAX_AREA_SHARE):
                continue
            if bw / width < self._MIN_DIM_SHARE or bh / height < self._MIN_DIM_SHARE:
                continue
            mask = labels == label
            center = (float(centers[label][0]), float(centers[label][1]))
            self._add_to_cluster(
                clusters,
                profile_index,
                mask,
                (x, y, bw, bh),
                center,
                area,
                diagonal,
            )

    @staticmethod
    def _bbox_iou(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
        ax0, ay0, aw, ah = a
        bx0, by0, bw, bh = b
        ax1, ay1 = ax0 + aw, ay0 + ah
        bx1, by1 = bx0 + bw, by0 + bh
        ix0, iy0 = max(ax0, bx0), max(ay0, by0)
        ix1, iy1 = min(ax1, bx1), min(ay1, by1)
        iw, ih = max(0, ix1 - ix0), max(0, iy1 - iy0)
        inter = iw * ih
        union = aw * ah + bw * bh - inter
        return inter / union if union > 0 else 0.0

    def _add_to_cluster(
        self,
        clusters: list[_Cluster],
        profile_index: int,
        mask: np.ndarray,
        bbox: tuple[int, int, int, int],
        center: tuple[float, float],
        area: int,
        diagonal: float,
    ) -> None:
        for cluster in clusters:
            cx, cy = cluster.center
            distance = ((center[0] - cx) ** 2 + (center[1] - cy) ** 2) ** 0.5
            if self._bbox_iou(bbox, cluster.bbox) >= 0.24 or distance <= diagonal * 0.05:
                cluster.members.append((profile_index, mask, bbox, center, area))
                return
        clusters.append(_Cluster(members=[(profile_index, mask, bbox, center, area)]))
