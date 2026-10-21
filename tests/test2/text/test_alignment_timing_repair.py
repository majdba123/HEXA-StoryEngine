"""Repair instead of stopping (2026-10-21): narration timing never stops a render.

Production salvages an unsafe word mapping by matching tokens to aligner words by text and
interpolating the rest; when even that is not enough (or the aligner is unavailable) the
service falls back to speech-interval timing, records why, and keywords stay on screen.
The strict contract (salvage/speech timing off) stays tested in
test_alignment_whitespace_normalization.py.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.models import Transcript, TranscriptWord
from app.text.timing.planner import TextTimingPlanner
from app.transcription.alignment import AlignmentRejectedError, WhisperXForcedAligner
from app.transcription.alignment.prepared_text import prepare_alignment_text
from app.transcription.service import RECOVERED_TIMING_SOURCE, TranscriptionService

SCRIPT = "الهاكر فتح الملف ثم سرق البيانات من الخادم وهرب بسرعة كبيرة جدا قبل أن يكتشفه أحد"


def _timed(words: list[str]) -> list[dict]:
    return [{"word": w, "start": 0.2 + 0.4 * n, "end": 0.5 + 0.4 * n} for n, w in enumerate(words)]


def test_one_misheard_word_is_interpolated_between_its_neighbours() -> None:
    words = SCRIPT.split(" ")
    raw = _timed([*words[:5], "شي_تاني", *words[6:]])
    transcript = WhisperXForcedAligner()._build_transcript(
        prepared=prepare_alignment_text(SCRIPT), language="ar", duration=10.0, raw_words=raw)
    assert [w.text for w in transcript.words] == words
    assert raw[4]["end"] <= transcript.words[5].start < transcript.words[5].end <= raw[6]["start"] + 1e-9


def test_an_extra_aligner_word_is_matched_by_text_not_zipped() -> None:
    words = SCRIPT.split(" ")
    raw = _timed([*words[:8], "زيادة", *words[8:]])
    aligner = WhisperXForcedAligner()
    transcript = aligner._build_transcript(prepared=prepare_alignment_text(SCRIPT), language="ar",
                                           duration=10.0, raw_words=raw)
    assert [w.text for w in transcript.words] == words
    assert transcript.words[8].start == pytest.approx(raw[9]["start"])  # after the extra word
    assert aligner.salvage_report is not None


def test_a_different_text_is_still_rejected_by_the_aligner() -> None:
    raw = _timed(["كلام", "مختلف", "تماما", "عن", "النص"] * 4)
    with pytest.raises(AlignmentRejectedError):
        WhisperXForcedAligner()._build_transcript(prepared=prepare_alignment_text(SCRIPT), language="ar",
                                                  duration=10.0, raw_words=raw)


class _RejectingAligner:
    def align(self, audio, script, duration):
        raise AlignmentRejectedError("unsafe", details={"code": "ALIGNMENT_WORD_MAPPING_UNSAFE"})


def test_the_service_recovers_with_speech_interval_timing_and_records_why(monkeypatch, tmp_path: Path) -> None:
    audio = tmp_path / "narration.mp3"
    audio.write_bytes(b"0")
    monkeypatch.setattr("app.transcription.service.probe_duration", lambda *_: 8.0)
    service = TranscriptionService(model_name="small", forced_aligner=_RejectingAligner(),
                                   require_forced_alignment=True)
    fallback = Transcript(language=None, duration=8.0, segments=[], timing_source="script_fallback",
                          words=[TranscriptWord(start=0.1, end=0.4, text="x", char_start=0, char_end=1)])
    monkeypatch.setattr(service, "_script_fallback", lambda *_: fallback.model_copy())
    transcript = service.transcribe(audio, SCRIPT)
    assert transcript.timing_source == RECOVERED_TIMING_SOURCE
    assert service.timing_repair["code"] == "ALIGNMENT_WORD_MAPPING_UNSAFE"


def test_strict_service_still_stops_when_speech_timing_is_off(monkeypatch, tmp_path: Path) -> None:
    audio = tmp_path / "narration.mp3"
    audio.write_bytes(b"0")
    monkeypatch.setattr("app.transcription.service.probe_duration", lambda *_: 8.0)
    service = TranscriptionService(model_name="small", forced_aligner=_RejectingAligner(),
                                   require_forced_alignment=True, recover_alignment=False)
    with pytest.raises(AlignmentRejectedError):
        service.transcribe(audio, SCRIPT)


def test_keywords_keep_their_place_on_recovered_timing() -> None:
    assert RECOVERED_TIMING_SOURCE in TextTimingPlanner.ACCEPTED_TIMING_SOURCES
    assert "script_fallback" not in TextTimingPlanner.ACCEPTED_TIMING_SOURCES
