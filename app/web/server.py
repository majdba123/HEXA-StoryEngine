from __future__ import annotations

import os
import shutil
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import Settings
from app.desktop.export_preflight import export_root_problem
from app.final_package.loader import FinalPackageLoader
from app.shared.errors import InvalidPackageError
from app.web.jobs import Jobs
from app.web.validation import validate_audio, validate_zip


def create_app(settings: Settings | None = None, storage: Path | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    storage = storage or Path(os.getenv("HEXA_WEB_STORAGE", ".hexa/web"))
    jobs = Jobs(storage, settings)
    max_upload = int(os.getenv("HEXA_WEB_MAX_UPLOAD_BYTES", str(2 * 1024**3)))

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        # Non-daemon workers finish shutdown before process exit. Cancellation is cooperative.

    app = FastAPI(title="HEXA Web", lifespan=lifespan)
    static = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=static), name="static")

    @app.get("/")
    def index():
        return FileResponse(static / "index.html")

    @app.get("/health")
    def health():
        return {"ok": True}

    async def save(upload: UploadFile, path: Path) -> None:
        size = 0
        with path.open("wb") as target:
            while chunk := await upload.read(1024 * 1024):
                size += len(chunk)
                if size > max_upload:
                    raise HTTPException(413, "Upload exceeds configured size limit")
                target.write(chunk)

    @app.post("/api/jobs", status_code=202)
    async def create_job(package: UploadFile = File(...), audio: UploadFile = File(...)):
        problem = export_root_problem(settings)
        if problem:
            raise HTTPException(422, problem)
        if not (package.filename or "").lower().endswith(".zip"):
            raise HTTPException(422, "Final Package must be a ZIP")
        suffix = Path(audio.filename or "").suffix.lower()
        if suffix not in {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg"}:
            raise HTTPException(422, "Unsupported audio type")
        job_id = jobs.create()
        if job_id is None:
            raise HTTPException(409, "A generation job is already active")
        directory = jobs.root / job_id
        package_path = directory / "package.zip"
        audio_path = directory / ("narration" + suffix)
        try:
            await save(package, package_path)
            await save(audio, audio_path)
            validate_zip(package_path)
            validate_audio(audio_path, settings.ffprobe_bin)
            FinalPackageLoader().load(package_path, directory / "validation")
            shutil.rmtree(directory / "validation", ignore_errors=True)
            jobs.start(job_id, package_path, audio_path)
        except InvalidPackageError as exc:
            jobs.update(job_id, state="failed", message="Input validation failed")
            shutil.rmtree(directory, ignore_errors=True)
            raise HTTPException(422, str(exc)) from exc
        except Exception:
            jobs.update(job_id, state="failed", message="Input validation failed")
            shutil.rmtree(directory, ignore_errors=True)
            raise
        return {"id": job_id, "state": "queued"}

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str):
        job = jobs.get(job_id)
        if job is None:
            raise HTTPException(404, "Job not found")
        return {key: job[key] for key in ("id", "state", "progress", "stage", "message")}

    @app.get("/api/jobs/{job_id}/events")
    def events(job_id: str):
        if jobs.get(job_id) is None:
            raise HTTPException(404, "Job not found")
        return jobs.events(job_id)

    @app.post("/api/jobs/{job_id}/cancel")
    def cancel(job_id: str):
        if jobs.get(job_id) is None:
            raise HTTPException(404, "Job not found")
        if not jobs.cancel(job_id):
            raise HTTPException(409, "Job is not active")
        return {"state": "cancelling"}

    @app.get("/api/jobs/{job_id}/download/{kind}")
    def download(job_id: str, kind: str):
        job = jobs.get(job_id)
        if job is None or job["state"] != "completed":
            raise HTTPException(404, "Completed job not found")
        bundle = Path(job["bundle"]).resolve()
        if kind in {"youtube", "reels"}:
            path = Path(job[kind]).resolve()
            if path.parent != bundle or path.suffix.lower() != ".mp4":
                raise HTTPException(404, "Output is unavailable")
            return FileResponse(path, filename=path.name, media_type="video/mp4")
        if kind == "manifest":
            return FileResponse(bundle / "export.json", filename="export.json")
        if kind == "diagnostics":
            path = jobs.root / job_id / "diagnostics.zip"
            report = jobs.report(job_id)
            if report is None:
                raise HTTPException(404, "Diagnostic report unavailable after server restart")
            report.export_zip(path)
            return FileResponse(path, filename=f"HEXA-diagnostic-{job_id[:8]}.zip")
        raise HTTPException(404, "Unknown output")

    return app


app = create_app()
