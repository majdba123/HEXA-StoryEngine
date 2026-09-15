from __future__ import annotations

import re
from pathlib import Path

from app.models import Transcript, TranscriptSegment
from app.shared.errors import DependencyUnavailableError
from app.shared.media import probe_duration


class TranscriptionService:
    def __init__(self, *, model_name: str, ffprobe_bin: str = "ffprobe") -> None:
        self.model_name = model_name
        self.ffprobe_bin = ffprobe_bin

    def transcribe(self, audio: Path, script: str | None = None) -> Transcript:
        audio = audio.expanduser().resolve()
        if not audio.exists():
            raise FileNotFoundError(audio)
        try:
            return self._faster_whisper(audio)
        except (ImportError, ModuleNotFoundError, DependencyUnavailableError):
            if script:
                return self._script_fallback(audio, script)
            raise DependencyUnavailableError(
                "faster-whisper is unavailable and Final Package has no script fallback"
            )

    def _faster_whisper(self, audio: Path) -> Transcript:
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise DependencyUnavailableError("faster-whisper is not installed") from exc
        model = WhisperModel(self.model_name, device="auto", compute_type="auto")
        segments_iter, info = model.transcribe(str(audio), vad_filter=True, word_timestamps=True)
        segments = [
            TranscriptSegment(start=float(seg.start), end=float(seg.end), text=seg.text.strip())
            for seg in segments_iter
            if seg.text.strip() and seg.end > seg.start
        ]
        duration = probe_duration(audio, self.ffprobe_bin)
        if not segments:
            raise DependencyUnavailableError("transcription produced no speech segments")
        return Transcript(language=getattr(info, "language", None), duration=duration, segments=segments)

    def _script_fallback(self, audio: Path, script: str) -> Transcript:
        duration = probe_duration(audio, self.ffprobe_bin)
        phrases = [p.strip() for p in re.split(r"(?<=[.!؟?،؛;])\s+|\n+", script) if p.strip()]
        if not phrases:
            phrases = [script.strip()]
        weights = [max(1, len(p.split())) for p in phrases]
        total = sum(weights)
        cursor = 0.0
        segments: list[TranscriptSegment] = []
        for index, (phrase, weight) in enumerate(zip(phrases, weights)):
            end = duration if index == len(phrases) - 1 else cursor + duration * weight / total
            end = max(end, cursor + 0.05)
            segments.append(TranscriptSegment(start=cursor, end=end, text=phrase))
            cursor = end
        return Transcript(language=None, duration=duration, segments=segments)
