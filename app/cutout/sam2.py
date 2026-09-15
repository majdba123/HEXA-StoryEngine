from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image


class SAM2CutoutBackend:
    def __init__(self, checkpoint: Path, config: str | None = None) -> None:
        import torch
        from sam2.build_sam import build_sam2
        from sam2.sam2_image_predictor import SAM2ImagePredictor

        self.torch = torch
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.checkpoint = checkpoint
        self.config = config or "configs/sam2.1/sam2.1_hiera_b+.yaml"
        self.predictor = SAM2ImagePredictor(
            build_sam2(
                self.config,
                str(checkpoint),
                device=self.device,
                apply_postprocessing=False,
            )
        )
        self._current_image: Path | None = None
        self._rgb: np.ndarray | None = None

    def cutout(self, image_path: Path, bbox: tuple[int, int, int, int]) -> Image.Image:
        image_path = image_path.resolve()
        if self._current_image != image_path:
            self._rgb = np.asarray(Image.open(image_path).convert("RGB"))
            self.predictor.set_image(self._rgb)
            self._current_image = image_path

        assert self._rgb is not None
        x, y, width, height = bbox
        box = np.asarray([x, y, x + width, y + height], dtype=np.float32)
        with self.torch.inference_mode():
            masks, scores, _ = self.predictor.predict(box=box, multimask_output=True)
        if len(masks) == 0:
            raise RuntimeError("SAM2 returned no masks")
        best = int(np.argmax(np.asarray(scores)))
        mask = np.asarray(masks[best], dtype=bool)
        rgba = np.dstack([self._rgb, (mask.astype(np.uint8) * 255)])
        image = Image.fromarray(rgba, mode="RGBA")
        alpha_box = image.getchannel("A").getbbox()
        if alpha_box is None:
            raise RuntimeError("SAM2 returned an empty mask")
        margin = 8
        left = max(0, alpha_box[0] - margin)
        top = max(0, alpha_box[1] - margin)
        right = min(image.width, alpha_box[2] + margin)
        bottom = min(image.height, alpha_box[3] + margin)
        return image.crop((left, top, right, bottom))
