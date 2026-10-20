"""Desktop job isolation: every generation runs in its own process.

The job's memory goes back to the operating system when that process exits, and a native
crash (the aligner's access violation once memory runs out) ends the job, not the panel.
The runners in ``tests.support.generation_jobs`` execute inside the real spawned process.
"""
from __future__ import annotations

import json
import os
import sys
import zipfile
from pathlib import Path

import pytest

from app.config import Settings
from app.desktop import job_process
from app.desktop.job_process import (
    GenerationJob,
    GenerationProcess,
    crash_retry_job,
    diagnostic_zip_path,
    out_of_memory_message,
)
from app.diagnostics import BuildReportSession
from app.models import Stage
from app.shared.errors import GenerationProcessCrashedError, StageFailedError
from app.shared.runtime_integrity import SOURCE_ROOT_ENV
from tests.support import generation_jobs


def _job(tmp_path: Path, job_id: str = "0123456789abcdef0123456789abcdef") -> GenerationJob:
    package = tmp_path / "HEXA_TEST_AR.zip"
    package.write_bytes(b"zip")
    audio = tmp_path / "narration.mp3"
    audio.write_bytes(b"mp3")
    settings = Settings(
        work_root=tmp_path / "work",
        output_root=tmp_path / "outputs",
        ffmpeg_bin="ffmpeg",
        ffprobe_bin="ffprobe",
        whisper_model="small",
        engine_host="127.0.0.1",
        engine_port=8765,
        allow_scene_fallback=False,
    )
    return GenerationJob(settings=settings, package_path=package, audio_path=audio, job_id=job_id)


def _report(job: GenerationJob) -> BuildReportSession:
    return BuildReportSession(
        job_id=job.job_id, settings=job.settings,
        package_path=job.package_path, audio_path=job.audio_path,
    )


def _zip_report(path: Path) -> dict:
    with zipfile.ZipFile(path) as archive:
        return json.loads(archive.read("report.json"))


def test_progress_is_forwarded_in_order_and_the_bundle_paths_come_back(tmp_path: Path) -> None:
    job = _job(tmp_path)
    seen: list[tuple] = []
    outcome = GenerationProcess(job, runner=generation_jobs.completes).run(
        lambda *event: seen.append(event)
    )

    assert seen == [
        (Stage.input, 0.005, "Checking export root"),
        (Stage.transcription, 0.12, generation_jobs.ARABIC_MESSAGE),
        (Stage.render, 0.97, "Rendering REELS_9_16"),
    ]
    directory = job.settings.work_root / "exports" / "HEXA_TEST_AR" / "v1"
    assert outcome.status == "completed" and outcome.exit_code == 0
    assert outcome.directory == str(directory)
    assert outcome.youtube == str(directory / "HEXA_TEST_AR_YOUTUBE.mp4")
    assert outcome.reels == str(directory / "HEXA_TEST_AR_REELS.mp4")

    # The report gets the same closing entries the in-process worker wrote.
    report = _report(job)
    outcome.record(report)
    assert report.status == "completed"
    assert report.output_path == Path(outcome.youtube).resolve()
    assert [event["message"] for event in report.stage_events] == [
        f"YOUTUBE_16_9: {outcome.youtube}",
        f"REELS_9_16: {outcome.reels}",
    ]
    assert not job.fault_log.exists()  # an empty fault log is not left behind


def test_cancel_reaches_the_job_process_at_its_safe_point(tmp_path: Path) -> None:
    job = _job(tmp_path)
    process = GenerationProcess(job, runner=generation_jobs.waits_for_cancel)
    outcome = process.run(lambda *_event: process.request_cancel())

    assert outcome.status == "cancelled" and outcome.exit_code == 0
    report = _report(job)
    outcome.record(report)
    assert report.status == "cancelled"


def test_closing_the_panel_stops_a_job_that_never_reaches_a_safe_point(tmp_path: Path) -> None:
    job = _job(tmp_path)
    process = GenerationProcess(job, runner=generation_jobs.ignores_cancel)
    outcome = process.run(lambda *_event: process.stop())

    assert outcome.status == "cancelled"
    assert outcome.exit_code != 0  # terminated, not finished


def test_a_python_failure_keeps_the_exact_diagnostic_record(tmp_path: Path) -> None:
    job = _job(tmp_path)
    outcome = GenerationProcess(job, runner=generation_jobs.fails).run(lambda *_event: None)

    assert outcome.status == "failed" and outcome.exit_code == 0
    local = BuildReportSession.describe_failure(StageFailedError(
        "forced alignment rejected",
        details={"code": "ALIGNMENT_REJECTED", "audio": Path.home() / "narration.mp3",
                 "words": ("مكان", "!!")},
    ))
    remote = dict(outcome.error)
    assert "in fails" in remote.pop("traceback")
    local.pop("traceback")
    assert remote == local  # identical to what the in-process worker recorded
    assert remote["details"]["audio"] == f"~{os.sep}narration.mp3"
    assert remote["policy"]["owner_stage"] == "transcription"

    report = _report(job)
    outcome.record(report)
    assert report.status == "failed" and report.error is outcome.error
    assert "FAILED: StageFailedError: forced alignment rejected" in report.log_path.read_text(
        encoding="utf-8")


def test_a_native_crash_becomes_a_typed_out_of_memory_failure_with_a_report(tmp_path: Path) -> None:
    job = _job(tmp_path)
    report = _report(job)
    outcome = GenerationProcess(job, runner=generation_jobs.crashes_natively).run(report.on_progress)

    assert outcome.status == "crashed"
    crash = outcome.crash
    assert isinstance(crash, GenerationProcessCrashedError)
    if sys.platform == "win32":
        assert outcome.exit_code == 0xC0000005
        assert crash.details["exit_status"] == "exit code 0xC0000005 STATUS_ACCESS_VIOLATION"
        assert crash.details["process_peak_private_bytes"] > 0
        assert crash.details["system_total_memory_bytes"] > 0
    else:
        assert outcome.exit_code is not None and outcome.exit_code < 0  # killed by a signal
    assert crash.details["likely_cause"] == "out_of_memory"
    assert crash.details["last_stage"] == "transcription"
    assert "crashes_natively" in crash.details["native_traceback"]  # where it died

    outcome.record(report)
    saved = report.export_zip(diagnostic_zip_path(report))
    assert saved == job.settings.work_root.resolve() / job.job_id / "HEXA-diagnostic-01234567.zip"
    payload = _zip_report(saved)
    assert payload["status"] == "failed"
    assert payload["last_stage"] == "transcription"
    assert payload["error"]["type"] == "GenerationProcessCrashedError"
    assert payload["error"]["code"] == "GENERATION_PROCESS_CRASHED"
    assert payload["error"]["policy"]["owner_stage"] == "pipeline"
    assert payload["error"]["details"]["likely_cause"] == "out_of_memory"


def test_the_out_of_memory_message_is_arabic_and_english_and_names_the_report() -> None:
    saved = Path("C:/HEXA/work/job/HEXA-diagnostic-01234567.zip")
    message = out_of_memory_message(saved)
    assert "نفدت" in message and "أغلق البرامج الثقيلة" in message
    assert "ran out of memory" in message and "Close heavy apps" in message
    assert message.count(str(saved)) == 2
    assert "استخراج تقرير التشخيص" in out_of_memory_message(None)


def test_job_memory_goes_back_to_the_os_when_the_job_ends(tmp_path: Path) -> None:
    job = _job(tmp_path)
    process = GenerationProcess(job, runner=generation_jobs.holds_memory)
    psutil = _optional_psutil()
    before = psutil.Process().memory_info().rss if psutil else None
    pids: list[int] = []
    outcome = process.run(lambda *_event: pids.append(process.pid))

    assert outcome.status == "completed" and outcome.exit_code == 0
    assert pids and pids[0] != os.getpid()  # the memory was held by another process
    if sys.platform == "win32":
        assert outcome.peak_private_bytes >= generation_jobs.HELD_BYTES
        assert "peak memory" in outcome.summary()
    if psutil:
        assert not psutil.pid_exists(pids[0])  # run() returns only after the process exited
        assert psutil.Process().memory_info().rss - before < generation_jobs.HELD_BYTES // 2


def test_the_job_process_refuses_another_checkout(tmp_path: Path, monkeypatch) -> None:
    other = tmp_path / "HEXA-StoryEngine-other"
    other.mkdir()
    monkeypatch.setenv(SOURCE_ROOT_ENV, str(other))
    outcome = GenerationProcess(_job(tmp_path), runner=generation_jobs.completes).run(
        lambda *_event: None
    )

    assert outcome.status == "failed"
    assert outcome.error["type"] == "RuntimeSourceMismatchError"


# The panel's QThread worker on top of the job process (needs the desktop extra) ----------
def test_panel_worker_emits_progress_and_finished_from_the_job_process(tmp_path: Path) -> None:
    pytest.importorskip("PySide6.QtWidgets")
    from app.desktop.main import GenerationWorker

    job = _job(tmp_path)
    report = _report(job)
    worker = _worker(GenerationWorker, job, report, generation_jobs.completes)
    events = _record_signals(worker)
    worker.run()

    directory = job.settings.work_root / "exports" / "HEXA_TEST_AR" / "v1"
    assert events == [
        ("progress", "input", 0, "Checking export root"),
        ("progress", "transcription", 12, generation_jobs.ARABIC_MESSAGE),
        ("progress", "render", 97, "Rendering REELS_9_16"),
        ("note", events[3][1]),
        ("finished", str(directory), str(directory / "HEXA_TEST_AR_YOUTUBE.mp4"),
         str(directory / "HEXA_TEST_AR_REELS.mp4")),
        ("done",),
    ]
    assert events[3][1].startswith("JOB PROCESS: completed (exit code 0)")
    assert report.status == "completed"
    assert [event["stage"] for event in report.stage_events] == [
        "input", "transcription", "render", "final", "final",
    ]


def test_panel_worker_reports_a_crash_and_writes_the_diagnostic_zip(tmp_path: Path) -> None:
    pytest.importorskip("PySide6.QtWidgets")
    from app.desktop.main import GenerationWorker

    job = _job(tmp_path)
    report = _report(job)
    worker = _worker(GenerationWorker, job, report, generation_jobs.crashes_natively)
    events = _record_signals(worker)
    worker.run()

    crashed = [event for event in events if event[0] == "crashed"]
    assert len(crashed) == 1 and events[-1] == ("done",)
    _, message, saved = crashed[0]
    assert Path(saved) == diagnostic_zip_path(report) and Path(saved).is_file()
    assert message == out_of_memory_message(Path(saved))
    assert any(event[0] == "note" and event[1].startswith("ERROR: The generation process stopped")
               for event in events)
    assert not any(event[0] in {"failed", "finished", "cancelled"} for event in events)
    assert _zip_report(Path(saved))["error"]["code"] == "GENERATION_PROCESS_CRASHED"


def test_the_retry_job_renders_with_one_worker_in_a_fresh_workspace(tmp_path: Path) -> None:
    job = _job(tmp_path)
    retry = crash_retry_job(job)
    assert retry.job_id == f"{job.job_id}-retry" and retry.fault_log != job.fault_log
    assert retry.settings.render_resources.workers_override == 1
    assert (retry.package_path, retry.audio_path) == (job.package_path, job.audio_path)
    assert retry.settings.work_root == job.settings.work_root


def test_panel_worker_retries_a_crashed_job_once_and_finishes(tmp_path: Path) -> None:
    pytest.importorskip("PySide6.QtWidgets")
    from app.desktop.main import GenerationWorker

    job = _job(tmp_path)
    report = _report(job)
    worker = _worker(GenerationWorker, job, report, generation_jobs.crashes_once)
    events = _record_signals(worker)
    worker.run()

    notes = [event[1] for event in events if event[0] == "note"]
    assert notes[0].startswith("JOB PROCESS: crashed")
    assert notes[1].startswith("RETRY:")
    assert notes[2].startswith("JOB PROCESS: completed")
    assert [event[0] for event in events if event[0] in {"finished", "crashed", "failed"}] == ["finished"]
    assert report.status == "completed"


def test_crash_retry_can_be_switched_off(tmp_path: Path, monkeypatch) -> None:
    pytest.importorskip("PySide6.QtWidgets")
    from app.desktop.main import GenerationWorker

    monkeypatch.setattr(job_process, "CRASH_RETRY", False)
    job = _job(tmp_path)
    worker = _worker(GenerationWorker, job, _report(job), generation_jobs.crashes_once)
    events = _record_signals(worker)
    worker.run()
    assert [event[0] for event in events if event[0] in {"finished", "crashed"}] == ["crashed"]
    assert not any(event[0] == "note" and event[1].startswith("RETRY:") for event in events)


def test_panel_worker_runs_the_premiere_job_in_its_own_process(tmp_path: Path) -> None:
    pytest.importorskip("PySide6.QtWidgets")
    from app.desktop.main import GenerationWorker

    job = _job(tmp_path)
    report = _report(job)
    worker = _worker(GenerationWorker, job, report, generation_jobs.premiere_completes)
    events = _record_signals(worker)
    worker.run()

    directory = job.settings.work_root / "exports" / "HEXA_TEST_AR" / "v1"
    finished = [event for event in events if event[0] == "finished"]
    assert finished == [("finished", str(directory), str(directory / "HEXA_TEST_AR_YOUTUBE_PREMIERE.xml"),
                         str(directory / "HEXA_TEST_AR_REELS_PREMIERE.xml"))]
    assert report.status == "completed"


def _worker(worker_class, job: GenerationJob, report: BuildReportSession, runner):
    return worker_class(
        settings=job.settings, package_path=job.package_path, audio_path=job.audio_path,
        report=report, runner=runner,
    )


def _record_signals(worker) -> list[tuple]:
    events: list[tuple] = []
    for name in ("progress", "note", "finished", "failed", "crashed", "cancelled", "done"):
        getattr(worker, name).connect(lambda *args, name=name: events.append((name, *args)))
    return events


def _optional_psutil():
    try:
        import psutil
    except ImportError:
        return None
    return psutil
