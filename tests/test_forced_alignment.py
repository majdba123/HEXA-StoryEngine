from pathlib import Path

import numpy as np
import pytest

from app.models import Transcript
from app.transcription.alignment import (
    AlignmentRejectedError,
    WhisperXForcedAligner,
    detect_script_language,
)
from app.transcription.alignment.whisperx import AlignmentPolicy
from app.transcription.service import TranscriptionService


def test_detect_script_language_supports_arabic_and_english() -> None:
    assert detect_script_language("الرصيد المتاح لا يساوي الرصيد الظاهر") == "ar"
    assert detect_script_language("The available balance is different") == "en"


def test_forced_alignment_builds_exact_arabic_script_mapping() -> None:
    aligner = WhisperXForcedAligner()
    script = "الرصيد المتاح، ثم البطاقة."
    raw_words = [
        {"word": "الرصيد", "start": 0.12, "end": 0.48, "score": 0.93},
        {"word": "المتاح،", "start": 0.52, "end": 0.88, "score": 0.91},
        {"word": "ثم", "start": 1.04, "end": 1.18, "score": 0.95},
        {"word": "البطاقة.", "start": 1.21, "end": 1.72, "score": 0.92},
    ]

    transcript = aligner._build_transcript(
        script=script,
        language="ar",
        duration=2.0,
        raw_words=raw_words,
    )

    assert [word.text for word in transcript.words] == ["الرصيد", "المتاح،", "ثم", "البطاقة."]
    assert transcript.words[0].char_start == 0
    assert transcript.words[-1].char_end == len(script)
    assert transcript.segments[0].start == pytest.approx(0.12)
    assert transcript.segments[-1].end == pytest.approx(1.72)


def test_forced_alignment_builds_exact_english_script_mapping() -> None:
    aligner = WhisperXForcedAligner()
    script = "Available balance, then the card."
    raw_words = [
        {"word": "Available", "start": 0.10, "end": 0.42},
        {"word": "balance,", "start": 0.45, "end": 0.76},
        {"word": "then", "start": 0.91, "end": 1.08},
        {"word": "the", "start": 1.10, "end": 1.20},
        {"word": "card.", "start": 1.22, "end": 1.54},
    ]

    transcript = aligner._build_transcript(
        script=script,
        language="en",
        duration=2.0,
        raw_words=raw_words,
    )

    assert len(transcript.words) == 5
    assert transcript.words[2].text == "then"
    assert transcript.words[2].start == pytest.approx(0.91)


def test_forced_alignment_rejects_shifted_word_mapping() -> None:
    aligner = WhisperXForcedAligner(policy=AlignmentPolicy(min_token_match_ratio=0.98))
    with pytest.raises(AlignmentRejectedError):
        aligner._build_transcript(
            script="one two three",
            language="en",
            duration=2.0,
            raw_words=[
                {"word": "one", "start": 0.1, "end": 0.3},
                {"word": "three", "start": 0.4, "end": 0.7},
                {"word": "two", "start": 0.8, "end": 1.0},
            ],
        )


def test_forced_alignment_rejects_non_monotonic_timestamps() -> None:
    aligner = WhisperXForcedAligner()
    with pytest.raises(AlignmentRejectedError):
        aligner._build_transcript(
            script="one two",
            language="en",
            duration=2.0,
            raw_words=[
                {"word": "one", "start": 0.5, "end": 0.9},
                {"word": "two", "start": 0.2, "end": 0.4},
            ],
        )


class _FakeForcedAligner:
    def __init__(self, transcript: Transcript) -> None:
        self.transcript = transcript
        self.calls: list[tuple[Path, str, float]] = []
        self.release_calls = 0

    def align(self, audio: Path, script: str, duration: float) -> Transcript:
        self.calls.append((audio, script, duration))
        return self.transcript

    def release(self) -> None:
        self.release_calls += 1


def test_transcription_prefers_forced_alignment_when_script_is_known(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"not-real-audio")
    expected = Transcript(language="en", duration=3.0, segments=[], words=[])
    fake = _FakeForcedAligner(expected)
    service = TranscriptionService(model_name="small", forced_aligner=fake)

    monkeypatch.setattr("app.transcription.service.probe_duration", lambda *_: 3.0)
    monkeypatch.setattr(
        service,
        "_faster_whisper",
        lambda *_: (_ for _ in ()).throw(AssertionError("ASR fallback must not run")),
    )

    result = service.transcribe(audio, "known script")

    assert result is expected
    assert len(fake.calls) == 1
    assert fake.calls[0][1] == "known script"
    assert fake.release_calls == 1


def test_whisperx_release_drops_cached_models(monkeypatch: pytest.MonkeyPatch) -> None:
    aligner = WhisperXForcedAligner()
    aligner._loaded["ar"] = (object(), {"language": "ar"})

    monkeypatch.setattr("gc.collect", lambda: 0)
    aligner.release()

    assert aligner._loaded == {}



def test_forced_alignment_passes_predecoded_waveform_to_whisperx(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    audio = tmp_path / "audio.mp3"
    audio.write_bytes(b"fake")
    waveform = np.asarray([0.0, 0.1, -0.1], dtype=np.float32)
    captured: dict[str, object] = {}

    def fake_decode(path: Path, ffmpeg_bin: str, *, sample_rate: int):
        captured["decode"] = (path, ffmpeg_bin, sample_rate)
        return waveform

    def fake_load_model(language: str, device: str, **kwargs):
        return object(), {"language": language, "dictionary": {}, "type": "huggingface"}

    def fake_align(source, model, metadata, audio_input, device, **kwargs):
        captured["audio_input"] = audio_input
        return {
            "word_segments": [
                {"word": "one", "start": 0.10, "end": 0.30},
                {"word": "two", "start": 0.40, "end": 0.70},
            ]
        }

    aligner = WhisperXForcedAligner(device="cpu", ffmpeg_bin="custom-ffmpeg")
    monkeypatch.setattr(
        "app.transcription.alignment.whisperx.decode_audio_mono",
        fake_decode,
    )
    monkeypatch.setattr(aligner, "_load_api", lambda: (fake_align, fake_load_model))

    transcript = aligner.align(audio, "one two", 1.0)

    assert captured["decode"] == (audio, "custom-ffmpeg", 16000)
    assert captured["audio_input"] is waveform
    assert [word.text for word in transcript.words] == ["one", "two"]
