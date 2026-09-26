from __future__ import annotations

from pathlib import Path

import pytest

from app.shared.errors import DependencyUnavailableError, StageFailedError
from app.transcription import TranscriptionService


class _PreflightAligner:
    def __init__(self) -> None:
        self.scripts: list[str] = []

    def preflight(self, script: str) -> None:
        self.scripts.append(script)

    def align(self, audio: Path, script: str, duration: float):
        raise AssertionError("align should not run during preflight")


def test_transcription_preflight_requires_audio_file(tmp_path: Path) -> None:
    service = TranscriptionService(model_name="small")
    with pytest.raises(StageFailedError) as exc_info:
        service.preflight(tmp_path / "missing.wav")
    assert exc_info.value.effective_code == "AUDIO_INPUT_MISSING"


def test_transcription_preflight_checks_strict_aligner(monkeypatch, tmp_path: Path) -> None:
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"fake")
    aligner = _PreflightAligner()
    service = TranscriptionService(
        model_name="small", forced_aligner=aligner, require_forced_alignment=True
    )
    monkeypatch.setattr("app.transcription.service.probe_duration", lambda *_args, **_kwargs: 1.25)

    duration = service.preflight(audio, "known script")

    assert duration == pytest.approx(1.25)
    assert aligner.scripts == ["known script"]


def test_transcription_preflight_rejects_strict_aligner_without_preflight(
    monkeypatch, tmp_path: Path
) -> None:
    class _AlignOnly:
        def align(self, audio: Path, script: str, duration: float):
            raise AssertionError

    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"fake")
    service = TranscriptionService(
        model_name="small", forced_aligner=_AlignOnly(), require_forced_alignment=True
    )
    monkeypatch.setattr("app.transcription.service.probe_duration", lambda *_args, **_kwargs: 1.0)

    with pytest.raises(DependencyUnavailableError) as exc_info:
        service.preflight(audio, "known script")

    assert exc_info.value.effective_code == "ALIGNMENT_PREFLIGHT_UNAVAILABLE"


def test_pipeline_writable_probe_removes_sentinel(tmp_path: Path) -> None:
    from app.pipeline import StoryEnginePipeline

    root = tmp_path / "new-dir"
    StoryEnginePipeline._assert_writable_directory(root, code="TEST_NOT_WRITABLE")
    assert root.is_dir()
    assert list(root.iterdir()) == []


def test_transcription_preflight_reports_missing_ffprobe(tmp_path: Path) -> None:
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"not-real-audio")
    service = TranscriptionService(
        model_name="small", ffprobe_bin="definitely-missing-ffprobe"
    )

    with pytest.raises(DependencyUnavailableError) as exc_info:
        service.preflight(audio)

    assert exc_info.value.effective_code == "FFPROBE_UNAVAILABLE"


def test_pipeline_writable_probe_wraps_os_error(monkeypatch, tmp_path: Path) -> None:
    from app.pipeline import StoryEnginePipeline

    def fail_write(_self: Path, _data: bytes) -> int:
        raise PermissionError("denied")

    monkeypatch.setattr(Path, "write_bytes", fail_write)
    with pytest.raises(StageFailedError) as exc_info:
        StoryEnginePipeline._assert_writable_directory(
            tmp_path / "blocked", code="OUTPUT_ROOT_NOT_WRITABLE"
        )

    assert exc_info.value.effective_code == "OUTPUT_ROOT_NOT_WRITABLE"
