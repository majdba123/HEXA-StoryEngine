from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.models import Transcript, TranscriptSegment, TranscriptWord
from app.shared.errors import DependencyUnavailableError
from app.shared.media import decode_audio_mono

_WORD_RE = re.compile(r"\S+")
_PHRASE_RE = re.compile(r"[^.!؟?،؛;\n]+[.!؟?،؛;]?|[^\n]+$")
_ARABIC_RE = re.compile(r"[\u0600-\u06FF]")
_LATIN_RE = re.compile(r"[A-Za-z]")
_ARABIC_DIACRITICS = re.compile(r"[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED]")

# Explicitly commercial-compatible alignment checkpoints. WhisperX itself is BSD-2-Clause.
# Both Hugging Face checkpoints below are Apache-2.0.
_DEFAULT_MODELS = {
    "ar": "jonatasgrosman/wav2vec2-large-xlsr-53-arabic",
    "en": "facebook/wav2vec2-base-960h",
}


class AlignmentRejectedError(RuntimeError):
    """Raised when an alignment result is structurally unsafe to trust."""


@dataclass(frozen=True, slots=True)
class AlignmentPolicy:
    min_token_match_ratio: float = 0.98
    timestamp_tolerance: float = 0.08


class WhisperXForcedAligner:
    """Forced-align a known script to narration using WhisperX CTC alignment.

    This class intentionally uses WhisperX only for alignment. The canonical Final Package
    script remains authoritative; ASR text is not substituted for it. Results are validated
    before they are allowed to drive Story/Motion timing.
    """

    def __init__(
        self,
        *,
        model_by_language: dict[str, str] | None = None,
        device: str | None = None,
        model_dir: Path | None = None,
        policy: AlignmentPolicy | None = None,
        ffmpeg_bin: str = "ffmpeg",
    ) -> None:
        self.model_by_language = {**_DEFAULT_MODELS, **(model_by_language or {})}
        self.device = device
        self.model_dir = model_dir
        self.policy = policy or AlignmentPolicy()
        self.ffmpeg_bin = ffmpeg_bin
        self._loaded: dict[str, tuple[Any, dict[str, Any]]] = {}

    def align(self, audio: Path, script: str, duration: float) -> Transcript:
        language = detect_script_language(script)
        model_name = self.model_by_language.get(language)
        if not model_name:
            raise AlignmentRejectedError(f"no forced-alignment model configured for {language}")

        align_fn, load_model = self._load_api()
        device = self.device or self._auto_device()
        model, metadata = self._model_for(
            language=language,
            model_name=model_name,
            device=device,
            load_model=load_model,
        )
        source = [{"start": 0.0, "end": duration, "text": script}]
        waveform = decode_audio_mono(audio, self.ffmpeg_bin, sample_rate=16000)
        try:
            result = align_fn(
                source,
                model,
                metadata,
                waveform,
                device,
                return_char_alignments=False,
                print_progress=False,
            )
        except Exception as exc:
            raise AlignmentRejectedError(f"forced alignment failed: {exc}") from exc

        raw_words = list(result.get("word_segments") or [])
        return self._build_transcript(
            script=script,
            language=language,
            duration=duration,
            raw_words=raw_words,
        )

    @staticmethod
    def _load_api():
        try:
            from whisperx.alignment import align, load_align_model
        except (ImportError, ModuleNotFoundError) as exc:
            raise DependencyUnavailableError(
                "WhisperX forced alignment is unavailable; install the alignment runtime"
            ) from exc
        return align, load_align_model

    @staticmethod
    def _auto_device() -> str:
        try:
            import torch
        except (ImportError, ModuleNotFoundError):
            return "cpu"
        return "cuda" if torch.cuda.is_available() else "cpu"

    def _model_for(self, *, language: str, model_name: str, device: str, load_model):
        cached = self._loaded.get(language)
        if cached is not None:
            return cached
        try:
            model, metadata = load_model(
                language,
                device,
                model_name=model_name,
                model_dir=str(self.model_dir) if self.model_dir else None,
            )
        except Exception as exc:
            raise DependencyUnavailableError(
                "forced-alignment model could not be loaded",
                details={"language": language, "model": model_name, "error": str(exc)},
            ) from exc
        self._loaded[language] = (model, metadata)
        return model, metadata

    def release(self) -> None:
        """Release cached alignment models after a completed transcription stage."""
        self._loaded.clear()

        # Clearing Python references is sufficient for correctness, but explicitly
        # collecting here prevents a multi-model pipeline from carrying large CPU
        # tensor graphs into Story/Florence on memory-constrained machines.
        import gc

        gc.collect()
        try:
            import torch
        except (ImportError, ModuleNotFoundError):
            return
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    def _build_transcript(
        self,
        *,
        script: str,
        language: str,
        duration: float,
        raw_words: list[dict[str, Any]],
    ) -> Transcript:
        token_matches = list(_WORD_RE.finditer(script))
        if not token_matches:
            raise AlignmentRejectedError("script contains no alignable words")
        if not raw_words:
            raise AlignmentRejectedError("forced aligner returned no word timestamps")

        # WhisperX 3.8.4+ preserves words containing digits/symbols with wildcard timing.
        # Still validate a one-to-one monotonic mapping so a bad model result can never
        # silently shift every subsequent word onto the wrong script token.
        comparable = min(len(token_matches), len(raw_words))
        matches = 0
        for index in range(comparable):
            expected = _normalize_token(token_matches[index].group())
            actual = _normalize_token(str(raw_words[index].get("word") or ""))
            if expected and actual and expected == actual:
                matches += 1
        match_ratio = matches / max(1, len(token_matches))
        if len(raw_words) != len(token_matches) or match_ratio < self.policy.min_token_match_ratio:
            raise AlignmentRejectedError(
                "forced alignment word mapping is unsafe "
                f"(script={len(token_matches)}, aligned={len(raw_words)}, match={match_ratio:.3f})"
            )

        words: list[TranscriptWord] = []
        previous_end = 0.0
        tolerance = self.policy.timestamp_tolerance
        for index, match in enumerate(token_matches):
            raw = raw_words[index]
            start = _float_or_none(raw.get("start"))
            end = _float_or_none(raw.get("end"))
            if start is None or end is None or end <= start:
                raise AlignmentRejectedError(f"missing/invalid timestamp for token {index}")
            if start + tolerance < previous_end:
                raise AlignmentRejectedError(f"non-monotonic timestamp at token {index}")
            if start < -tolerance or end > duration + tolerance:
                raise AlignmentRejectedError(f"timestamp outside audio duration at token {index}")
            start = max(0.0, start)
            end = min(duration, end)
            words.append(TranscriptWord(
                start=start,
                end=end,
                text=match.group(),
                char_start=match.start(),
                char_end=match.end(),
            ))
            previous_end = end

        segments = _segments_from_script(script, words)
        if not segments:
            segments = [TranscriptSegment(
                start=words[0].start,
                end=words[-1].end,
                text=script.strip(),
                char_start=0,
                char_end=len(script),
                words=words,
            )]
        return Transcript(language=language, duration=duration, segments=segments, words=words)


def detect_script_language(script: str) -> str:
    """Return the dominant supported alignment language for Arabic/English scripts."""
    arabic = len(_ARABIC_RE.findall(script))
    latin = len(_LATIN_RE.findall(script))
    if arabic == 0 and latin == 0:
        raise AlignmentRejectedError("script has no Arabic or English letters")
    return "ar" if arabic >= latin else "en"


def _segments_from_script(script: str, words: list[TranscriptWord]) -> list[TranscriptSegment]:
    segments: list[TranscriptSegment] = []
    for phrase in [match for match in _PHRASE_RE.finditer(script) if match.group().strip()]:
        overlapping = [
            word
            for word in words
            if word.char_start is not None
            and word.char_end is not None
            and word.char_end > phrase.start()
            and word.char_start < phrase.end()
        ]
        if not overlapping:
            continue
        segments.append(TranscriptSegment(
            start=overlapping[0].start,
            end=overlapping[-1].end,
            text=phrase.group().strip(),
            char_start=phrase.start(),
            char_end=phrase.end(),
            words=overlapping,
        ))
    return segments


def _normalize_token(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).lower().replace("ـ", "")
    value = _ARABIC_DIACRITICS.sub("", value)
    return "".join(character for character in value if character.isalnum())


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None
