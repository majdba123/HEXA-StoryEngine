"""Deterministic stand-ins for the WhisperX 3.8.6 alignment call.

``whisperx_words`` reproduces the word-boundary rule of ``whisperx.alignment.align`` for
languages with spaces: a new word starts only after an ASCII space (``text.split(" ")``,
``text[cdx + 1] == " "``) and each word's text is ``"".join(chars).strip()``. Any other
whitespace (newline, tab, NBSP, ...) stays INSIDE the word, which is exactly why a
formatted canonical script must never be sent verbatim.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from app.transcription.alignment import WhisperXForcedAligner


def whisperx_words(text: str) -> list[str]:
    words = [piece.strip() for piece in text.split(" ")]
    return [word for word in words if word]


def timed_words(words: list[str], duration: float, *, offset: float = 0.05) -> list[dict[str, Any]]:
    """Evenly spaced, strictly monotonic word timestamps inside ``duration``."""
    slot = (duration - 2 * offset) / max(1, len(words))
    output = []
    for index, word in enumerate(words):
        start = round(offset + index * slot, 4)
        end = round(start + slot * 0.8, 4)
        output.append({"word": word, "start": start, "end": end, "score": 0.9})
    return output


class FakeWhisperX:
    """Captures the text handed to WhisperX and answers with WhisperX-like words."""

    def __init__(
        self,
        duration: float,
        *,
        splitter: Callable[[str], list[str]] = whisperx_words,
        transform: Callable[[list[dict[str, Any]]], list[dict[str, Any]]] | None = None,
    ) -> None:
        self.duration = duration
        self.splitter = splitter
        self.transform = transform
        self.received_texts: list[str] = []

    def load_model(self, language: str, device: str, **_kwargs):
        return object(), {"language": language, "dictionary": {}, "type": "huggingface"}

    def align(self, source, _model, _metadata, _audio, _device, **_kwargs):
        text = source[0]["text"]
        self.received_texts.append(text)
        words = timed_words(self.splitter(text), self.duration)
        if self.transform is not None:
            words = self.transform(words)
        return {"word_segments": words}


def fake_aligner(
    monkeypatch: pytest.MonkeyPatch,
    duration: float,
    **kwargs: Any,
) -> tuple[WhisperXForcedAligner, FakeWhisperX]:
    fake = FakeWhisperX(duration, **kwargs)
    aligner = WhisperXForcedAligner(device="cpu")
    monkeypatch.setattr(
        "app.transcription.alignment.whisperx.decode_audio_mono",
        lambda *_a, **_k: object(),
    )
    monkeypatch.setattr(aligner, "_load_api", lambda: (fake.align, fake.load_model))
    return aligner, fake


def audio_stub(tmp_path: Path) -> Path:
    audio = tmp_path / "narration.mp3"
    audio.write_bytes(b"fake")
    return audio
