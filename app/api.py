from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI, HTTPException, status

from app.models import JobRequest, JobSnapshot, JobState, Stage
from app.pipeline import StoryEnginePipeline
from app.shared.errors import HexaError


class JobStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, JobSnapshot] = {}

    def create(self) -> JobSnapshot:
        job = JobSnapshot(id=uuid.uuid4().hex, state=JobState.queued, message="Queued")
        with self._lock:
            self._jobs[job.id] = job
        return job

    def get(self, job_id: str) -> JobSnapshot | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return job.model_copy(deep=True) if job else None

    def update(self, job_id: str, **changes) -> None:
        with self._lock:
            current = self._jobs[job_id]
            self._jobs[job_id] = current.model_copy(update=changes)


app = FastAPI(title="HEXA StoryEngine", version="0.1.0")
_store = JobStore()
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="hexa-storyengine")


@app.get("/health")
def health() -> dict:
    return {"ok": True, "service": "HEXA StoryEngine", "version": "0.1.0"}


@app.post("/jobs", response_model=JobSnapshot, status_code=status.HTTP_202_ACCEPTED)
def create_job(request: JobRequest) -> JobSnapshot:
    job = _store.create()
    _executor.submit(_run_job, job.id, request)
    return job


@app.get("/jobs/{job_id}", response_model=JobSnapshot)
def get_job(job_id: str) -> JobSnapshot:
    job = _store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job_not_found")
    return job


def _run_job(job_id: str, request: JobRequest) -> None:
    try:
        engine = StoryEnginePipeline()
        _store.update(job_id, state=JobState.running, progress=0.01, message="Starting")

        def progress(stage: Stage, value: float, message: str) -> None:
            _store.update(
                job_id,
                state=JobState.running,
                stage=stage,
                progress=value,
                message=message,
            )

        output = engine.generate(
            package_path=_path(request.package_path),
            audio_path=_path(request.audio_path),
            script_path=_path(request.script_path) if request.script_path else None,
            output_name=request.output_name,
            job_id=job_id,
            progress=progress,
        )
        _store.update(
            job_id,
            state=JobState.completed,
            stage=Stage.final,
            progress=1.0,
            message="Ready for Premiere",
            output_path=str(output),
        )
    except HexaError as exc:
        _store.update(
            job_id,
            state=JobState.failed,
            progress=1.0,
            message=str(exc),
            error_code=exc.code,
        )
    except Exception as exc:
        _store.update(
            job_id,
            state=JobState.failed,
            progress=1.0,
            message=f"Unexpected engine failure: {exc}",
            error_code="UNEXPECTED_ENGINE_FAILURE",
        )


def _path(raw: str):
    from pathlib import Path

    return Path(raw).expanduser().resolve()
