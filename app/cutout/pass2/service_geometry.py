from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from app.models import VisualAsset
from app.cutout.pass2.models import CandidateProposal


class _GeometryHelpersMixin:
    def _allow_hard_core_fallback(
        self,
        rgba: np.ndarray,
        candidate: CandidateProposal,
        dominant: CandidateProposal,
        *,
        hard_contact: bool,
    ) -> bool:
        height, width = rgba.shape[:2]
        _x, _y, bw, bh = candidate.bbox
        height_share = bh / max(1, height)
        width_share = bw / max(1, width)
        aspect = bh / max(1, bw)
        moat = self.validator.external_moat_score(rgba, candidate)
        if moat < 0.94 or candidate.stability < (4 / 7):
            return False
        if not hard_contact:
            return True

        # Hard-contact fallback has two safe shapes:
        # 1) a large external figure/object (for example a person crossed by a scan
        #    beam or ground shadow), or
        # 2) a compact external object whose hard connection disappears after a tiny
        #    morphological opening, which indicates a weak shadow/bridge rather than a
        #    real fused attachment.
        tall_external = (
            candidate.area_share >= 0.075
            and height_share >= 0.58
            and 0.07 <= width_share <= 0.46
            and aspect >= 1.15
        )
        compact_external = (
            candidate.area_share >= 0.07
            and min(bw / max(1, width), bh / max(1, height)) >= 0.10
            and 0.50 <= aspect <= 2.00
            and self._hard_bridge_is_weak(rgba, candidate, dominant)
        )
        return tall_external or compact_external

    @staticmethod
    def _hard_bridge_is_weak(
        rgba: np.ndarray,
        candidate: CandidateProposal,
        dominant: CandidateProposal,
    ) -> bool:
        alpha = rgba[:, :, 3]
        hsv = cv2.cvtColor(rgba[:, :, :3], cv2.COLOR_RGB2HSV)
        contact = (
            (alpha >= 28)
            & ((hsv[:, :, 1] >= 18) | (hsv[:, :, 2] <= 212))
        ).astype(np.uint8) * 255
        opened = cv2.morphologyEx(
            contact,
            cv2.MORPH_OPEN,
            cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)),
            iterations=1,
        )
        _, labels = cv2.connectedComponents((opened > 0).astype(np.uint8), connectivity=8)
        candidate_labels = {
            int(value)
            for value in np.unique(labels[candidate.core_mask])
            if int(value) > 0
        }
        dominant_labels = {
            int(value)
            for value in np.unique(labels[dominant.core_mask])
            if int(value) > 0
        }
        # If a 5px opening breaks the shared label, the original connection was a
        # weak shadow/very thin bridge. Robust physical attachments survive it.
        return not bool(candidate_labels & dominant_labels)

    @staticmethod
    def _candidate_allowed_for_target(candidate, shape: tuple[int, int], target_types: list[str]) -> bool:
        # Semantic target types influence ranking only. They must never suppress a
        # geometrically detached object; this layer is product-wide object recovery.
        return True

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
