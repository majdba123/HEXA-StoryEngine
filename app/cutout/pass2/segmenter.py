from __future__ import annotations

from pathlib import Path
from typing import Protocol

import numpy as np
from PIL import Image


class MaskBackend(Protocol):
    def segment(self, image_path: Path, bbox: tuple[int, int, int, int]) -> np.ndarray | None: ...


class SAM2MaskBackend:
    """Lazy full-canvas SAM2 mask backend. Missing runtime deps fail closed."""

    def __init__(self, checkpoint: Path, config: str | None = None) -> None:
        self.checkpoint = checkpoint
        self.config = config or "configs/sam2.1/sam2.1_hiera_b+.yaml"
        self._predictor = None
        self._torch = None
        self._current_image: Path | None = None
        self._failed = False

    def _ensure(self) -> bool:
        if self._failed or not self.checkpoint.is_file():
            return False
        if self._predictor is not None:
            return True
        try:
            import torch
            from sam2.build_sam import build_sam2
            from sam2.sam2_image_predictor import SAM2ImagePredictor

            device = "cuda" if torch.cuda.is_available() else "cpu"
            self._predictor = SAM2ImagePredictor(
                build_sam2(
                    self.config,
                    str(self.checkpoint),
                    device=device,
                    apply_postprocessing=False,
                )
            )
            self._torch = torch
            return True
        except Exception:
            self._failed = True
            return False

    def segment(self, image_path: Path, bbox: tuple[int, int, int, int]) -> np.ndarray | None:
        if not self._ensure():
            return None
        assert self._predictor is not None
        assert self._torch is not None
        image_path = image_path.resolve()
        rgb = np.asarray(Image.open(image_path).convert("RGB"))
        if self._current_image != image_path:
            self._predictor.set_image(rgb)
            self._current_image = image_path
        x, y, width, height = bbox
        box = np.asarray([x, y, x + width, y + height], dtype=np.float32)
        try:
            with self._torch.inference_mode():
                masks, scores, _ = self._predictor.predict(box=box, multimask_output=True)
        except Exception:
            return None
        if len(masks) == 0:
            return None
        best = int(np.argmax(np.asarray(scores)))
        mask = np.asarray(masks[best], dtype=bool)
        return mask if mask.shape == rgb.shape[:2] and np.any(mask) else None
