"""The real WhisperX alignment code with a stub acoustic model.

``alignment_fake`` reproduces WhisperX's space rule only; it never ran WhisperX's Punkt
sentence grouping, which is how a token such as ``"مكان!!,"`` came back as two words in
production. Here the production ``WhisperXForcedAligner.align`` drives the installed
``whisperx.alignment.align`` end to end: real character cleaning and wildcard columns, real
CTC trellis and backtrack, real Punkt sentence spans and word grouping. Only the wav2vec2
network is replaced by seeded random log-probabilities over the real model vocabulary, so
timings are arbitrary but every structural decision WhisperX makes is its own.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import numpy as np

from app.models import Transcript
from app.transcription.alignment import WhisperXForcedAligner
from app.transcription.alignment.prepared_text import prepare_alignment_text
from app.transcription.alignment.whisperx import detect_script_language

# jonatasgrosman/wav2vec2-large-xlsr-53-arabic vocab.json, as WhisperX lower-cases it.
ARABIC_DICTIONARY = {
    "<pad>": 0, "<s>": 1, "</s>": 2, "<unk>": 3, "|": 4, "-": 5,
    **{char: 6 + index for index, char in enumerate(
        "ءآأؤإئابةتثجحخدذرزسشصضطظعغـفقكلمنهوىيًٌٍَُِّْ"
    )},
}
# facebook/wav2vec2-base-960h characters (WhisperX lower-cases the vocabulary).
ENGLISH_DICTIONARY = {
    "<pad>": 0, "<s>": 1, "</s>": 2, "<unk>": 3, "|": 4, "'": 5,
    **{char: 6 + index for index, char in enumerate("etaonihsrdlumwcfgypbvkxjqz")},
}
SAMPLE_RATE = 16_000
FRAME_SAMPLES = 320  # wav2vec2 emits one frame per 20 ms


def runtime_align(script: str, *, seed: int = 0, module: Any = None) -> Transcript:
    """Align ``script`` through the production aligner and the installed WhisperX code.

    ``module`` is the aligner module to drive (default: production); a test may pass an
    older copy to compare behaviours on the same WhisperX run.
    """
    import torch
    from whisperx.alignment import align as whisperx_align

    module = module or __import__("app.transcription.alignment.whisperx", fromlist=["x"])
    language = detect_script_language(script)
    dictionary = ARABIC_DICTIONARY if language == "ar" else ENGLISH_DICTIONARY
    frames = 2 * len(prepare_alignment_text(script).text) + 64
    waveform = np.zeros(frames * FRAME_SAMPLES, dtype=np.float32)
    duration = waveform.size / SAMPLE_RATE
    vocabulary = max(dictionary.values()) + 1

    class _Acoustic(torch.nn.Module):
        def forward(self, audio):
            generator = torch.Generator().manual_seed(seed)
            steps = max(1, audio.shape[-1] // FRAME_SAMPLES)
            return SimpleNamespace(logits=torch.randn(1, steps, vocabulary, generator=generator))

    def load_model(language_code, device, **_kwargs):
        return _Acoustic(), {"language": language_code, "dictionary": dictionary, "type": "huggingface"}

    aligner: WhisperXForcedAligner = module.WhisperXForcedAligner(device="cpu")
    aligner._load_api = lambda: (whisperx_align, load_model)
    with patch.object(module, "decode_audio_mono", lambda *_args, **_kwargs: waveform):
        return aligner.align(Path("runtime-stub.wav"), script, duration)


def raw_runtime_words(script: str, *, seed: int = 0) -> list[dict[str, Any]]:
    """The words WhisperX itself returns for ``script`` (before any HEXA mapping)."""
    import torch
    from whisperx.alignment import align as whisperx_align

    language = detect_script_language(script)
    dictionary = ARABIC_DICTIONARY if language == "ar" else ENGLISH_DICTIONARY
    text = prepare_alignment_text(script).text
    frames = 2 * len(text) + 64
    waveform = np.zeros(frames * FRAME_SAMPLES, dtype=np.float32)
    vocabulary = max(dictionary.values()) + 1

    class _Acoustic(torch.nn.Module):
        def forward(self, audio):
            generator = torch.Generator().manual_seed(seed)
            return SimpleNamespace(logits=torch.randn(1, audio.shape[-1] // FRAME_SAMPLES, vocabulary,
                                                      generator=generator))

    result = whisperx_align(
        [{"start": 0.0, "end": waveform.size / SAMPLE_RATE, "text": text}], _Acoustic(),
        {"language": language, "dictionary": dictionary, "type": "huggingface"}, waveform, "cpu",
        return_char_alignments=False, print_progress=False,
    )
    return list(result.get("word_segments") or [])
