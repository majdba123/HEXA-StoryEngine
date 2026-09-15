from __future__ import annotations

import numpy as np


class PartitionSafetyGate:
    """Hard invariants: same canvas, exact alpha reconstruction, zero overlap."""

    def validate(self, original_alpha: np.ndarray, secondary_masks: list[np.ndarray]) -> bool:
        if not secondary_masks:
            return False
        shape = original_alpha.shape
        if any(mask.shape != shape for mask in secondary_masks):
            return False

        union = np.zeros(shape, dtype=bool)
        for mask in secondary_masks:
            if np.any(union & mask):
                return False
            union |= mask
        if not np.any(union):
            return False

        main = np.where(union, 0, original_alpha).astype(np.uint8)
        if not np.any(main):
            return False
        reconstructed = main.copy()
        for mask in secondary_masks:
            secondary = np.where(mask, original_alpha, 0).astype(np.uint8)
            reconstructed = np.maximum(reconstructed, secondary)
        return bool(np.array_equal(reconstructed, original_alpha))
