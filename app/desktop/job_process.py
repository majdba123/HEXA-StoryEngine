"""Run one generation job in its own child process.

The forced aligner alone peaks near 6.7 GB, and a long-lived panel process keeps most of
the memory a job touched. A fresh process per job hands every byte back to the operating
system when it exits. A native crash in that process (an access violation once memory
runs out) then ends the job, not the panel: the panel reports it as a typed failure and
still writes the diagnostic report.

This module is Qt-free so the job protocol is testable without a display.
"""
from __future__ import annotations

import ctypes
import faulthandler
import json
import multiprocessing
import os
import signal
import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass
from multiprocessing.connection import Connection, wait
from pathlib import Path
from typing import Any

from app.config import Settings
from app.diagnostics import BuildReportSession
from app.models import Stage
from app.shared.errors import GenerationCancelledError, GenerationProcessCrashedError
from app.shared.runtime_integrity import RuntimeSourceMismatchError, require_launch_source, source_root

ProgressCallback = Callable[[Stage, float, str], None]
CancellationCallback = Callable[[], bool]

# Seconds the child may take to exit after its last message before it is terminated.
EXIT_GRACE_SECONDS = 30.0
FAULT_LOG_NAME = "process-fault.log"
_FAULT_LOG_LIMIT = 20_000

_WINDOWS_EXIT_STATUS = {
    0xC0000005: "STATUS_ACCESS_VIOLATION",
    0xC0000017: "STATUS_NO_MEMORY",
    0xC000001D: "STATUS_ILLEGAL_INSTRUCTION",
    0xC00000FD: "STATUS_STACK_OVERFLOW",
    0xC000012D: "STATUS_COMMITMENT_LIMIT",
    0xC0000374: "STATUS_HEAP_CORRUPTION",
    0xC0000409: "STATUS_STACK_BUFFER_OVERRUN",
}


@dataclass(frozen=True, slots=True)
class GenerationJob:
    settings: Settings
    package_path: Path
    audio_path: Path
    job_id: str

    @property
    def fault_log(self) -> Path:
        return self.settings.work_root / self.job_id / FAULT_LOG_NAME


Runner = Callable[[GenerationJob, ProgressCallback, CancellationCallback], Any]


def run_pipeline(job: GenerationJob, progress: ProgressCallback, cancelled: CancellationCallback):
    """The production job; imported and run in the child process only."""
    from app.pipeline import StoryEnginePipeline

    pipeline = StoryEnginePipeline(job.settings)
    return pipeline.generate_bundle(
        package_path=job.package_path,
        audio_path=job.audio_path,
        job_id=job.job_id,
        progress=progress,
        cancelled=cancelled,
    )


@dataclass(slots=True)
class GenerationOutcome:
    """How one job process ended; ``status`` is completed, cancelled, failed or crashed."""

    status: str
    exit_code: int | None
    peak_private_bytes: int | None = None
    directory: str | None = None
    youtube: str | None = None
    reels: str | None = None
    outputs: tuple[tuple[str, str], ...] = ()
    error: dict[str, Any] | None = None
    crash: GenerationProcessCrashedError | None = None

    @property
    def message(self) -> str:
        if self.crash is not None:
            return str(self.crash)
        return str((self.error or {}).get("message") or "")

    def summary(self) -> str:
        """One panel log line: how the job process ended and the memory it peaked at."""
        peak = (
            f", peak memory {self.peak_private_bytes / 2**30:.2f} GB"
            if self.peak_private_bytes is not None
            else ""
        )
        return f"JOB PROCESS: {self.status} ({_exit_status(self.exit_code)}){peak}"

    def record(self, report: BuildReportSession) -> None:
        """Write this outcome into the panel's diagnostic report."""
        if self.status == "completed":
            for target_id, path in self.outputs:
                report.on_progress(Stage.final, 1.0, f"{target_id}: {path}")
            report.complete(Path(self.youtube or ""))
        elif self.status == "cancelled":
            report.cancel()
        elif self.status == "failed":
            report.record_failure(self.error or {})
        else:
            report.fail(self.crash or GenerationProcessCrashedError("generation process crashed"))


class GenerationProcess:
    """Parent side of one job: start the child, forward progress, map how it ended."""

    def __init__(self, job: GenerationJob, *, runner: Runner = run_pipeline) -> None:
        self.job = job
        self._runner = runner
        self._context = multiprocessing.get_context("spawn")
        self._cancel = self._context.Event()
        self._lock = threading.Lock()
        self._process: multiprocessing.process.BaseProcess | None = None
        self._stopped = False
        self.pid: int | None = None

    def request_cancel(self) -> None:
        """Cooperative cancel: the job stops at its next safe point, as before."""
        self._cancel.set()

    def stop(self) -> None:
        """Terminate the job now (the panel is closing)."""
        with self._lock:
            self._stopped = True
            self._cancel.set()
            if self._process is not None and self._process.is_alive():
                self._process.terminate()

    def run(self, on_progress: ProgressCallback) -> GenerationOutcome:
        """Run the job to its end; returns only after the child process has exited."""
        receiver, sender = self._context.Pipe(duplex=False)
        process = self._context.Process(
            target=_child_main,
            args=(sender, self._cancel, self.job, str(source_root()), self._runner),
            name=f"hexa-job-{self.job.job_id[:8]}",
            # Not daemonic: libraries inside a job may start processes of their own.
            daemon=False,
        )
        with self._lock:
            if self._stopped:
                receiver.close()
                sender.close()
                return GenerationOutcome(status="cancelled", exit_code=None)
            process.start()
            self._process = process
            self.pid = process.pid
        sender.close()  # the child holds the only writer: its exit reads as end-of-file
        terminal: tuple | None = None
        last: tuple[str, str] | None = None
        try:
            while terminal is None:
                ready = wait([receiver, process.sentinel])
                if receiver not in ready and not receiver.poll(0):
                    break  # exited and nothing is left to read
                try:
                    message = receiver.recv()
                except EOFError:
                    break
                if message[0] == "progress":
                    _, stage, value, text = message
                    last = (stage, text)
                    on_progress(Stage(stage), value, text)
                else:
                    terminal = message
        finally:
            receiver.close()
            process.join(EXIT_GRACE_SECONDS if terminal is not None else 0)
            if process.is_alive():
                process.terminate()
            process.join()
        peak = _peak_private_bytes(process.sentinel)
        exit_code = process.exitcode
        with self._lock:
            self._process = None
        process.close()
        return self._outcome(terminal, exit_code, peak, last)

    def _outcome(
        self,
        terminal: tuple | None,
        exit_code: int | None,
        peak: int | None,
        last: tuple[str, str] | None,
    ) -> GenerationOutcome:
        if terminal is not None:
            kind, payload = terminal
            if kind == "completed":
                return GenerationOutcome(
                    status="completed", exit_code=exit_code, peak_private_bytes=peak,
                    directory=payload["directory"], youtube=payload["youtube"],
                    reels=payload["reels"],
                    outputs=tuple((str(a), str(b)) for a, b in payload["outputs"]),
                )
            if kind == "cancelled":
                return GenerationOutcome(status="cancelled", exit_code=exit_code, peak_private_bytes=peak)
            return GenerationOutcome(status="failed", exit_code=exit_code, peak_private_bytes=peak,
                                     error=payload)
        if self._stopped:
            return GenerationOutcome(status="cancelled", exit_code=exit_code, peak_private_bytes=peak)
        return GenerationOutcome(
            status="crashed", exit_code=exit_code, peak_private_bytes=peak,
            crash=_crash_error(self.job, exit_code, peak, last),
        )


def diagnostic_zip_path(report: BuildReportSession) -> Path:
    """Where a crashed job's diagnostic report is written automatically."""
    return report.log_path.parent / f"HEXA-diagnostic-{report.job_id[:8]}.zip"


def out_of_memory_message(report_path: Path | None) -> str:
    """The panel's bilingual explanation of a crashed job process."""
    if report_path is not None:
        saved_ar = f"تم حفظ تقرير التشخيص هنا:\n{report_path}"
        saved_en = f"The diagnostic report was saved to:\n{report_path}"
    else:
        saved_ar = "تعذر حفظ تقرير التشخيص تلقائياً؛ استخدم زر «استخراج تقرير التشخيص»."
        saved_en = "The diagnostic report could not be saved automatically; use the export button."
    return (
        "توقفت عملية التوليد فجأة لأن ذاكرة الجهاز (RAM) نفدت.\n"
        "أغلق البرامج الثقيلة مثل Firefox ثم أعد التوليد. "
        "اللوحة ما زالت تعمل ولا تحتاج لإعادة تشغيل.\n"
        f"{saved_ar}\n\n"
        "The render process stopped because the computer ran out of memory (RAM).\n"
        "Close heavy apps such as Firefox, then generate again. "
        "The panel is still running and does not need a restart.\n"
        f"{saved_en}"
    )


# -- child process ------------------------------------------------------------------------
def _child_main(
    conn: Connection,
    cancel: Any,
    job: GenerationJob,
    expected_source: str,
    runner: Runner,
) -> None:
    lock = threading.Lock()

    def send(message: tuple) -> None:
        with lock:
            conn.send(message)

    def progress(stage: Stage, value: float, message: str) -> None:
        send(("progress", stage.value, float(value), message))

    _exit_with_parent()
    _no_crash_dialog()
    fault = _enable_fault_log(job.fault_log)
    try:
        try:
            require_launch_source()
            if source_root() != Path(expected_source):
                raise RuntimeSourceMismatchError(
                    f"The panel runs the engine from {expected_source} but its job process "
                    f"imported {source_root()}."
                )
            bundle = runner(job, progress, cancel.is_set)
            send(("completed", {
                "directory": str(bundle.directory),
                "youtube": str(bundle.youtube.path),
                "reels": str(bundle.reels.path),
                "outputs": [(output.target_id, str(output.path)) for output in bundle.outputs.values()],
            }))
        except GenerationCancelledError:
            send(("cancelled", None))
        except Exception as exc:  # noqa: BLE001 - reported to the panel and its diagnostic report
            error = BuildReportSession.describe_failure(exc)
            try:
                send(("failed", error))
            except Exception:  # noqa: BLE001 - details that cannot be pickled are sent as text
                send(("failed", json.loads(json.dumps(error, default=str))))
        conn.close()
    except BaseException:
        _close_fault_log(fault, job.fault_log)
        os._exit(1)
    _close_fault_log(fault, job.fault_log)
    # Everything is reported and the bundle is published. Skip interpreter teardown: it
    # can take long with torch loaded, and a native library crashing at exit must not
    # turn a finished job into a failed one.
    os._exit(0)


def _exit_with_parent() -> None:
    """An orphaned job must not keep gigabytes of memory: leave when the panel is gone."""
    parent = multiprocessing.parent_process()
    if parent is None:
        return

    def watch() -> None:
        wait([parent.sentinel])
        os._exit(1)

    threading.Thread(target=watch, name="hexa-parent-watch", daemon=True).start()


def _no_crash_dialog() -> None:
    """A crashed job must end at once so the panel can report it, not wait on a dialog."""
    if sys.platform == "win32":
        kernel32 = ctypes.WinDLL("kernel32")
        kernel32.SetErrorMode(kernel32.GetErrorMode() | 0x0002)  # SEM_NOGPFAULTERRORBOX


def _enable_fault_log(path: Path):
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = path.open("w", encoding="utf-8")
    except OSError:
        return None
    faulthandler.enable(file=handle, all_threads=True)
    return handle


def _close_fault_log(handle, path: Path) -> None:
    if handle is None:
        return
    faulthandler.disable()
    handle.close()
    try:
        if path.stat().st_size == 0:
            path.unlink()
    except OSError:
        pass


# -- crash mapping ------------------------------------------------------------------------
def _crash_error(
    job: GenerationJob,
    exit_code: int | None,
    peak: int | None,
    last: tuple[str, str] | None,
) -> GenerationProcessCrashedError:
    status = _exit_status(exit_code)
    stage = last[0] if last else None
    memory = _system_memory()
    details: dict[str, Any] = {
        "exit_code": exit_code,
        "exit_status": status,
        "likely_cause": "out_of_memory",
        "last_stage": stage,
        "last_message": last[1] if last else None,
        "process_peak_private_bytes": peak,
        "system_total_memory_bytes": memory[0] if memory else None,
        "system_available_memory_bytes": memory[1] if memory else None,
        "native_traceback": _read_fault_log(job.fault_log),
    }
    where = f" during {stage}" if stage else ""
    return GenerationProcessCrashedError(
        f"The generation process stopped without an error report ({status}){where}. "
        "The computer most likely ran out of memory.",
        details=details,
    )


def _exit_status(exit_code: int | None) -> str:
    if exit_code is None:
        return "exit code unknown"
    if exit_code < 0:
        try:
            return f"signal {signal.Signals(-exit_code).name}"
        except ValueError:
            return f"signal {-exit_code}"
    if exit_code > 0xFFFF:
        code = exit_code & 0xFFFFFFFF
        name = _WINDOWS_EXIT_STATUS.get(code)
        return f"exit code 0x{code:08X}" + (f" {name}" if name else "")
    return f"exit code {exit_code}"


def _read_fault_log(path: Path) -> str | None:
    try:
        text = path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None
    return text[-_FAULT_LOG_LIMIT:] or None


class _ProcessMemoryCounters(ctypes.Structure):
    _fields_ = [
        ("cb", ctypes.c_ulong),
        ("PageFaultCount", ctypes.c_ulong),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


class _MemoryStatus(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def _peak_private_bytes(process_handle: int) -> int | None:
    """Peak committed private memory of a (possibly exited) Windows process."""
    if sys.platform != "win32":
        return None
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    query = kernel32.K32GetProcessMemoryInfo
    query.argtypes = [ctypes.c_void_p, ctypes.POINTER(_ProcessMemoryCounters), ctypes.c_ulong]
    query.restype = ctypes.c_int
    counters = _ProcessMemoryCounters()
    counters.cb = ctypes.sizeof(counters)
    if not query(ctypes.c_void_p(process_handle), ctypes.byref(counters), counters.cb):
        return None
    return int(counters.PeakPagefileUsage)


def _system_memory() -> tuple[int, int] | None:
    """(total, available) physical memory in bytes on Windows."""
    if sys.platform != "win32":
        return None
    status = _MemoryStatus()
    status.dwLength = ctypes.sizeof(status)
    if not ctypes.WinDLL("kernel32").GlobalMemoryStatusEx(ctypes.byref(status)):
        return None
    return int(status.ullTotalPhys), int(status.ullAvailPhys)
