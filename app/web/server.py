from __future__ import annotations

import os
import shutil
import json
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
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

    async def save_folder(files: list[UploadFile], paths_json: str, path: Path) -> None:
        try:
            paths = json.loads(paths_json)
        except ValueError as exc:
            raise HTTPException(422, "Invalid directory listing") from exc
        if not isinstance(paths, list) or len(paths) != len(files) or not 0 < len(paths) <= 5000:
            raise HTTPException(422, "Invalid directory file count")
        names: set[str] = set()
        total = 0
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for upload, raw in zip(files, paths):
                if not isinstance(raw, str):
                    raise HTTPException(422, "Invalid directory path")
                name = raw.replace("\\", "/")
                parts = name.split("/")
                if (name.startswith("/") or len(parts) < 2 or
                        any(p in ("", ".", "..") for p in parts) or ":" in parts[0] or
                        name in names):
                    raise HTTPException(422, "Unsafe directory path")
                names.add(name)
                with archive.open(name, "w") as target:
                    while chunk := await upload.read(1024 * 1024):
                        total += len(chunk)
                        if total > max_upload:
                            raise HTTPException(413, "Directory exceeds configured size limit")
                        target.write(chunk)

    @app.post("/api/jobs", status_code=202)
    async def create_job(audio: UploadFile = File(...), package: UploadFile | None = File(None),
                         folder_files: list[UploadFile] | None = File(None),
                         folder_paths: str | None = Form(None)):
        problem = export_root_problem(settings)
        if problem:
            raise HTTPException(422, problem)
        if bool(package) == bool(folder_files):
            raise HTTPException(422, "Select one ZIP or one folder")
        if package and not (package.filename or "").lower().endswith(".zip"):
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
            if package:
                await save(package, package_path)
            else:
                await save_folder(folder_files or [], folder_paths or "", package_path)
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
        result = {key: job[key] for key in ("id", "state", "progress", "stage", "message")}
        if job["state"] == "completed":
            result["export_directory"] = job["bundle"]
        return result

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
