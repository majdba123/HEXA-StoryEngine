"""Local, narration-blind visual inventory backend. Never downloads weights."""
from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any

from PIL import Image


_LOG = logging.getLogger(__name__)


def parse_json_object(response: str) -> dict[str, Any] | None:
    """Decode the first complete object, including nested/quoted braces."""
    decoder = json.JSONDecoder()
    for index, char in enumerate(response):
        if char != "{":
            continue
        try:
            value, _ = decoder.raw_decode(response, index)
        except ValueError:
            continue
        if isinstance(value, dict):
            return value
    return None


class SmolVLMBackend:
    backend_name = "smolvlm"
    max_assets_per_request = 6
    inventory_contract_version = 2

    @staticmethod
    def inventory_prompt(assets) -> str:
        ids = [asset.id for asset in assets]
        return (
            'Describe the labelled cutouts. JSON only, no markdown or explanation. '
            'Use exact allowed asset IDs; never invent IDs. Short visual descriptions. '
            'Return {"assets":[{"asset_id":"ID","description":"visible object/action",'
            '"category":"object","semantic":true,"confidence":0.9}]}. '
            'Use semantic=false for decorative or unclear cutouts. Confidence: 0 to 1. '
            f'Allowed asset IDs: {json.dumps(ids)}'
        )

    def __init__(self, model_path: str | None = None) -> None:
        self.model_path = model_path
        self._processor = None
        self._model = None
        self._failed = False
        self._lock = threading.Lock()
        self.runtime_available: bool | None = None if self.enabled else False
        self.runtime_error: str | None = None
        self.inference_seconds: float | None = None
        self.response_length = 0
        self.response_preview = ""

    @property
    def enabled(self) -> bool:
        return bool(self.model_path and self.model_path.strip())

    def _load(self) -> None:
        if self._model is not None:
            return
        path = Path(self.model_path).expanduser()
        if not path.is_dir():
            raise FileNotFoundError(f"SmolVLM local model directory not found: {path}")
        import torch
        from transformers import AutoModelForVision2Seq, AutoProcessor

        processor = AutoProcessor.from_pretrained(str(path), local_files_only=True)
        # Idefics3Processor in transformers 4.57 drops this kwarg when passed to
        # __call__; configure the image processor itself to bound CPU image tokens.
        processor.image_processor.do_image_splitting = False
        model = AutoModelForVision2Seq.from_pretrained(
            str(path), local_files_only=True, torch_dtype=torch.float32,
        )
        model.to("cpu")
        model.eval()
        self._processor, self._model = processor, model

    def decide(self, image_path: Path, prompt: str) -> dict[str, Any] | None:
        if not self.enabled or self._failed:
            return None
        with self._lock:
            if self._failed:
                return None
            self.response_length = 0
            self.response_preview = ""
            started = time.perf_counter()
            try:
                self._load()
                import torch

                messages = [{"role": "user", "content": [
                    {"type": "image"}, {"type": "text", "text": prompt},
                ]}]
                text = self._processor.apply_chat_template(messages, add_generation_prompt=True)
                with Image.open(image_path) as source:
                    image = source.convert("RGB")
                try:
                    image.thumbnail((1024, 1024))
                    inputs = self._processor(
                        text=text, images=[image], return_tensors="pt",
                    )
                finally:
                    image.close()
                with torch.inference_mode():
                    generated = self._model.generate(
                        **inputs, do_sample=False, num_beams=1, max_new_tokens=2048,
                    )
                trimmed = generated[:, inputs["input_ids"].shape[1]:]
                response = self._processor.batch_decode(trimmed, skip_special_tokens=True)[0]
                self.runtime_available = True
                self.runtime_error = None
                self.response_length = len(response)
                self.response_preview = response[:1500]
                parsed = parse_json_object(response)
                if parsed is None:
                    self.runtime_error = "invalid_json_response"
                    return None
                return parsed
            except Exception as exc:
                self.runtime_available = False
                self.runtime_error = f"{type(exc).__name__}: {exc}"
                self._failed = True
                self._model = self._processor = None
                _LOG.warning("SMOLVLM_RUNTIME_UNAVAILABLE: %s", self.runtime_error)
                return None
            finally:
                self.inference_seconds = time.perf_counter() - started
                _LOG.info("SmolVLM inventory inference_seconds=%.3f", self.inference_seconds)
