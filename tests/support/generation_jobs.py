"""Job runners for the desktop job-process tests. They run inside the spawned job process.

Each one has the production runner's signature and returns the production result types,
so the parent sees exactly what ``StoryEnginePipeline.generate_bundle`` would send.
"""
from __future__ import annotations

import ctypes
import sys
import time
from pathlib import Path

from app.models import Stage
from app.pipeline import GenerationBundleResult, PremiereBundleResult, PremiereOutput, TargetOutput
from app.shared.errors import GenerationCancelledError, StageFailedError

ARABIC_MESSAGE = "محاذاة السرد: «مكان!!،» جاهز"
HELD_BYTES = 400 * 2**20


def _bundle(job) -> GenerationBundleResult:
    directory = job.settings.work_root / "exports" / "HEXA_TEST_AR" / "v1"
    directory.mkdir(parents=True, exist_ok=True)
    outputs = {}
    for target_id, suffix, size in (("YOUTUBE_16_9", "YOUTUBE", (1920, 1080)),
                                    ("REELS_9_16", "REELS", (1080, 1920))):
        path = directory / f"HEXA_TEST_AR_{suffix}.mp4"
        path.write_bytes(b"mp4")
        outputs[target_id] = TargetOutput(
            target_id=target_id, path=path, width=size[0], height=size[1], fps=30,
            duration=1.0, frame_count=30, render_plan_path=directory / f"{suffix}.json",
            render_plan_fingerprint="0" * 64, encoded_motion_ok=True, final_media_ok=True,
            media={}, seconds=0.1, worker_count=1,
        )
    return GenerationBundleResult(
        package_id="HEXA_TEST_AR", slug="HEXA_TEST_AR", version=1, directory=directory,
        manifest_path=directory / "export.json", outputs=outputs,
    )


def completes(job, progress, cancelled):
    progress(Stage.input, 0.005, "Checking export root")
    progress(Stage.transcription, 0.12, ARABIC_MESSAGE)
    progress(Stage.render, 0.97, "Rendering REELS_9_16")
    return _bundle(job)


def waits_for_cancel(job, progress, cancelled):
    progress(Stage.transcription, 0.12, "Aligning narration")
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if cancelled():
            # The pipeline's own safe-point check raises exactly this.
            raise GenerationCancelledError("generation cancelled by user")
        time.sleep(0.02)
    raise AssertionError("cancel never arrived")


def ignores_cancel(job, progress, cancelled):
    """Long native work (the aligner) never reaches a safe point."""
    progress(Stage.transcription, 0.12, "Aligning narration")
    time.sleep(60)
    return _bundle(job)


def fails(job, progress, cancelled):
    progress(Stage.transcription, 0.12, "Aligning narration")
    raise StageFailedError(
        "forced alignment rejected",
        details={"code": "ALIGNMENT_REJECTED", "audio": Path.home() / "narration.mp3",
                 "words": ("مكان", "!!")},
    )


def crashes_natively(job, progress, cancelled):
    """A real access violation in native code, as when wav2vec2 runs out of memory."""
    progress(Stage.transcription, 0.12, "Aligning narration")
    if sys.platform == "win32":
        # ctypes turns a fault inside its own calls into OSError, so fault in a native
        # thread (like torch's compute threads): strlen(NULL) reads address 0.
        kernel32 = ctypes.WinDLL("kernel32")
        kernel32.CreateThread.restype = ctypes.c_void_p
        kernel32.CreateThread.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p,
                                          ctypes.c_void_p, ctypes.c_ulong, ctypes.c_void_p]
        strlen = ctypes.cast(ctypes.cdll.msvcrt.strlen, ctypes.c_void_p)
        kernel32.CreateThread(None, 0, strlen, None, 0, None)
        time.sleep(30)
    else:
        ctypes.string_at(0)
    raise AssertionError("still alive after a native crash")


def holds_memory(job, progress, cancelled):
    held = bytearray(HELD_BYTES)
    for offset in range(0, len(held), 4096):
        held[offset] = 1  # touch every page so it is really committed
    progress(Stage.render, 0.5, "holding memory")
    return _bundle(job)


def crashes_once(job, progress, cancelled):
    """A native crash on the first attempt; the panel's automatic retry completes."""
    if not job.job_id.endswith("-retry"):
        crashes_natively(job, progress, cancelled)
    if job.settings.render_resources.workers_override != 1:
        raise AssertionError("the retry must render with one worker")
    return completes(job, progress, cancelled)


def premiere_completes(job, progress, cancelled):
    """The Premiere job's result shape: one FCP7 XML per format in the bundle."""
    progress(Stage.render, 0.6, "Youtube: Writing Premiere layers")
    directory = job.settings.work_root / "exports" / "HEXA_TEST_AR" / "v1"
    directory.mkdir(parents=True, exist_ok=True)
    outputs = {}
    for target_id, suffix in (("YOUTUBE_16_9", "YOUTUBE"), ("REELS_9_16", "REELS")):
        path = directory / f"HEXA_TEST_AR_{suffix}_PREMIERE.xml"
        path.write_text("<xmeml version=\"4\"/>", encoding="utf-8")
        outputs[target_id] = PremiereOutput(target_id=target_id, path=path, tracks=3, clips=4)
    return PremiereBundleResult(package_id="HEXA_TEST_AR", slug="HEXA_TEST_AR", version=1, directory=directory,
                                manifest_path=directory / "export.json", outputs=outputs)
