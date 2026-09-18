from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class Qwen3VLBackend:
    """Optional local Qwen3-VL backend.

    The backend is deliberately isolated: it proposes semantic intent only and never
    owns pixel coordinates. Layout safety remains deterministic even when a VLM is used.
    """

    def __init__(self, model_path: str | None = None) -> None:
        self.model_path = model_path
        self._model = None
        self._processor = None

    @property
    def enabled(self) -> bool:
        return bool(self.model_path)

    def decide(self, image_path: Path, prompt: str) -> dict[str, Any] | None:
        if not self.enabled:
            return None
        self._load()
        try:
            messages = [{
                "role": "user",
                "content": [
                    {"type": "image", "image": str(image_path)},
                    {"type": "text", "text": prompt},
                ],
            }]
            inputs = self._processor.apply_chat_template(
                messages,
                tokenize=True,
                add_generation_prompt=True,
                return_dict=True,
                return_tensors="pt",
            )
            if hasattr(self._model, "device"):
                inputs = {k: v.to(self._model.device) if hasattr(v, "to") else v for k, v in inputs.items()}
            generated = self._model.generate(**inputs, max_new_tokens=320)
            trimmed = generated[:, inputs["input_ids"].shape[1]:]
            text = self._processor.batch_decode(trimmed, skip_special_tokens=True)[0]
            start = text.find("{")
            end = text.rfind("}")
            if start < 0 or end <= start:
                return None
            parsed = json.loads(text[start:end + 1])
            return parsed if isinstance(parsed, dict) else None
        except Exception:
            return None

    def _load(self) -> None:
        if self._model is not None:
            return
        try:
            from transformers import AutoProcessor, Qwen3VLForConditionalGeneration
        except ImportError as exc:  # pragma: no cover - optional runtime
            raise RuntimeError("Qwen3-VL runtime is not installed") from exc
        self._processor = AutoProcessor.from_pretrained(self.model_path)
        self._model = Qwen3VLForConditionalGeneration.from_pretrained(
            self.model_path,
            device_map="auto",
            torch_dtype="auto",
        )
