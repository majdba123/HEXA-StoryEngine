"""Final exporter keeps FFmpeg's localized stderr readable (Windows cp1252 regression)."""
from __future__ import annotations

import sys

import pytest

from app.final import exporter as exporter_module
from app.final.exporter import FinalExporter
from app.shared.errors import StageFailedError
from app.shared.process import run_hidden

# "ف" encodes as D9 81 in UTF-8; cp1252 has no 0x81, which is the byte the 2026-10-16
# final encode logs failed on.
ARABIC_NAME = "فيديو عربي"

# Stands in for ffmpeg in a real child process: writes the output file, then
# FFmpeg-style stderr that echoes the Arabic output path as UTF-8, followed by bytes
# that are not valid UTF-8 at all (raw localized metadata).
FAKE_FFMPEG = r'''
import sys
from pathlib import Path

target = Path(sys.argv[1])
target.write_bytes(b"\x00" * 64)
sys.stderr.buffer.write(f"Output #0, mp4, to '{target}':\n".encode("utf-8"))
sys.stderr.buffer.write(b"\xff\xfe broken metadata\n")
sys.stderr.buffer.flush()
sys.exit(int(sys.argv[2]))
'''


def _fake_ffmpeg(monkeypatch, exit_code: int) -> list:
    """Run the exporter's real run_hidden kwargs against FAKE_FFMPEG."""
    completed: list = []

    def fake_run_hidden(command, **kwargs):
        assert command[0] == "ffmpeg"
        child = [sys.executable, "-c", FAKE_FFMPEG, command[-1], str(exit_code)]
        result = run_hidden(child, **kwargs)
        completed.append(result)
        return result

    monkeypatch.setattr(exporter_module, "run_hidden", fake_run_hidden)
    return completed


def _preflight(exporter: FinalExporter, tmp_path):
    return exporter.preflight(tmp_path / "rendered.mp4", tmp_path / ARABIC_NAME)


def _mux(exporter: FinalExporter, tmp_path):
    return exporter.mux(
        tmp_path / "rendered.mp4",
        tmp_path / "narration.wav",
        tmp_path / ARABIC_NAME / f"{ARABIC_NAME}.mp4",
    )


CASES = [
    pytest.param(_preflight, "FINAL_MUX_PREFLIGHT_FAILED", id="preflight"),
    pytest.param(_mux, "FINAL_MUX_FAILED", id="mux"),
]


@pytest.mark.parametrize(("run", "_code"), CASES)
def test_success_decodes_localized_stderr_without_error(monkeypatch, tmp_path, run, _code):
    completed = _fake_ffmpeg(monkeypatch, exit_code=0)

    output = run(FinalExporter("ffmpeg"), tmp_path)

    assert output.is_file()
    # A failed locale reader thread leaves stderr as None; it must be decoded text.
    stderr = completed[0].stderr
    assert isinstance(stderr, str)
    assert ARABIC_NAME in stderr
    assert "� broken metadata" in stderr


@pytest.mark.parametrize(("run", "code"), CASES)
def test_failure_keeps_readable_stderr_in_error(monkeypatch, tmp_path, run, code):
    _fake_ffmpeg(monkeypatch, exit_code=1)

    with pytest.raises(StageFailedError) as caught:
        run(FinalExporter("ffmpeg"), tmp_path)

    assert caught.value.details["code"] == code
    stderr = caught.value.details["stderr"]
    assert ARABIC_NAME in stderr
    assert "� broken metadata" in stderr
