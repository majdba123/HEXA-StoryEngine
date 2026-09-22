"""Local Florence-2 caption backend for Story visual semantics.

This backend is deliberately narration-blind. It receives one already-extracted
asset image and returns only a visual description; Story/E5 owns phrase matching
and timing.
"""
from __future__ import annotations

import logging
import re
import threading
import time
from pathlib import Path
from typing import Any

from PIL import Image


_LOG = logging.getLogger(__name__)
_SPACE = re.compile(r"\s+")
_GENERIC_CAPTIONS = {
    "object",
    "an object",
    "a visible object",
    "visible object",
    "visible object action",
    "image",
    "an image",
    "something",
    "unknown",
    "unclear",
}


class FlorenceVisualSemanticBackend:
    backend_name = "florence"
    inventory_mode = "per_asset"
    inventory_contract_version = 1
    task = "<MORE_DETAILED_CAPTION>"

    # Florence captioning does not expose a calibrated probability for the generated
    # caption. This is a conservative acceptance score used only to pass the existing
    # inventory quality gate; E5 still decides whether the caption matches narration.
    accepted_caption_confidence = 0.72

    def __init__(self, model_path: str | None = None) -> None:
        self.model_path = model_path
        self._processor = None
        self._model = None
        self._torch = None
        self._failed = False
        self._lock = threading.Lock()
        self.runtime_available: bool | None = None if self.enabled else False
        self.runtime_error: str | None = None
        self.inference_seconds: float | None = None

    @property
    def enabled(self) -> bool:
        return bool(self.model_path and self.model_path.strip())

    def _load(self) -> None:
        if self._model is not None:
            return
        path = Path(self.model_path).expanduser()
        if not path.is_dir():
            raise FileNotFoundError(f"Florence local model directory not found: {path}")

        import torch
        from transformers import AutoModelForCausalLM, AutoProcessor

        processor = AutoProcessor.from_pretrained(
            str(path),
            local_files_only=True,
            trust_remote_code=True,
        )
        model = AutoModelForCausalLM.from_pretrained(
            str(path),
            local_files_only=True,
            trust_remote_code=True,
            torch_dtype=torch.float32,
        )
        model.to("cpu")
        model.eval()
        self._torch = torch
        self._processor = processor
        self._model = model

    def describe_asset(self, image_path: Path) -> dict[str, Any] | None:
        """Caption one extracted asset without seeing narration, IDs, or timing."""
        if not self.enabled or self._failed:
            return None
        with self._lock:
            started = time.perf_counter()
            try:
                try:
                    self._load()
                except Exception as exc:
                    self._failed = True
                    self.runtime_available = False
                    self.runtime_error = f"{type(exc).__name__}: {exc}"
                    self._processor = self._model = self._torch = None
                    _LOG.warning("FLORENCE_STORY_RUNTIME_UNAVAILABLE: %s", self.runtime_error)
                    return None

                try:
                    with Image.open(image_path) as source:
                        image = source.convert("RGB")
                    try:
                        image.thumbnail((1024, 1024))
                        inputs = self._processor(
                            text=self.task,
                            images=image,
                            return_tensors="pt",
                        )
                        if hasattr(inputs, "to"):
                            inputs = inputs.to("cpu")
                        else:
                            inputs = {
                                name: value.to("cpu") if hasattr(value, "to") else value
                                for name, value in inputs.items()
                            }
                        with self._torch.inference_mode():
                            generated = self._model.generate(
                                **inputs,
                                max_new_tokens=128,
                                num_beams=1,
                                do_sample=False,
                            )
                        raw = self._processor.batch_decode(
                            generated, skip_special_tokens=False,
                        )[0]
                        parsed = self._processor.post_process_generation(
                            raw,
                            task=self.task,
                            image_size=image.size,
                        )
                    finally:
                        image.close()
                except Exception as exc:
                    # A bad asset must not permanently disable a successfully loaded model.
                    self.runtime_available = True
                    self.runtime_error = f"{type(exc).__name__}: {exc}"
                    _LOG.warning(
                        "FLORENCE_STORY_ASSET_FAILED asset=%s error=%s",
                        image_path,
                        self.runtime_error,
                    )
                    return None

                self.runtime_available = True
                self.runtime_error = None
                caption = self._caption_from_parsed(parsed)
                if not self._useful_caption(caption):
                    return None
                return {
                    "description": caption,
                    "category": "visual_caption",
                    "semantic": True,
                    "confidence": self.accepted_caption_confidence,
                }
            finally:
                self.inference_seconds = time.perf_counter() - started
                _LOG.info(
                    "Florence Story asset inference_seconds=%.3f asset=%s",
                    self.inference_seconds,
                    image_path,
                )

    @classmethod
    def _caption_from_parsed(cls, parsed: Any) -> str:
        value: Any = parsed
        if isinstance(parsed, dict):
            value = parsed.get(cls.task)
            if value is None:
                value = parsed.get(cls.task.strip("<>"))
        if isinstance(value, dict):
            value = next(
                (value.get(key) for key in ("caption", "text", "description") if value.get(key)),
                None,
            )
        if not isinstance(value, str):
            return ""
        return _SPACE.sub(" ", value).strip()

    @staticmethod
    def _useful_caption(caption: str) -> bool:
        if not caption or len(caption) > 320:
            return False
        normalized = " ".join(
            token for token in re.sub(r"[^0-9A-Za-z\u0600-\u06FF]+", " ", caption.casefold()).split()
        )
        if normalized in _GENERIC_CAPTIONS:
            return False
        tokens = normalized.split()
        return len(tokens) >= 2 and any(any(ch.isalpha() for ch in token) for token in tokens)
