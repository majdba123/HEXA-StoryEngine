from __future__ import annotations

from pathlib import Path

from PIL import Image


class FlorenceDetector:
    def __init__(self, model_path: Path) -> None:
        import torch
        from transformers import AutoModelForCausalLM, AutoProcessor

        self.torch = torch
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        dtype = torch.float16 if self.device == "cuda" else torch.float32
        self.processor = AutoProcessor.from_pretrained(
            str(model_path),
            local_files_only=True,
            trust_remote_code=True,
        )
        self.model = AutoModelForCausalLM.from_pretrained(
            str(model_path),
            local_files_only=True,
            trust_remote_code=True,
            torch_dtype=dtype,
            # Keep Florence on eager attention for compatibility with the
            # remote-code implementation across supported Transformers 4.x.
            attn_implementation="eager",
        ).to(self.device).eval()

    def detect(self, image_path: Path) -> list[tuple[str, tuple[int, int, int, int], float]]:
        image = Image.open(image_path).convert("RGB")
        parsed = self._run(image, "<OD>")
        boxes = parsed.get("bboxes") or parsed.get("quad_boxes") or []
        labels = parsed.get("labels") or []
        output: list[tuple[str, tuple[int, int, int, int], float]] = []
        for index, raw_box in enumerate(boxes):
            if len(raw_box) < 4:
                continue
            x0, y0, x1, y1 = [int(round(float(value))) for value in raw_box[:4]]
            if x1 <= x0 or y1 <= y0:
                continue
            label = str(labels[index] if index < len(labels) else "object")
            output.append((label, (x0, y0, x1 - x0, y1 - y0), 0.72))
        return output

    def _run(self, image: Image.Image, task: str) -> dict:
        inputs = self.processor(text=task, images=image, return_tensors="pt")
        inputs = {name: value.to(self.device) for name, value in inputs.items()}
        with self.torch.inference_mode():
            generated = self.model.generate(
                **inputs,
                max_new_tokens=1024,
                num_beams=3,
                do_sample=False,
            )
        text = self.processor.batch_decode(generated, skip_special_tokens=False)[0]
        parsed = self.processor.post_process_generation(text, task=task, image_size=image.size)
        row = parsed.get(task, {}) if isinstance(parsed, dict) else {}
        return row if isinstance(row, dict) else {}
