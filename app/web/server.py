from __future__ import annotations

import os
import shutil
import json
import zipfile
import asyncio
import hashlib
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Body, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import Settings
from app.desktop.export_preflight import export_root_problem
from app.final_package.loader import FinalPackageLoader
from app.shared.errors import InvalidPackageError
from app.web.jobs import Jobs
from app.web.security import SECURITY_HEADERS, SESSION_COOKIE, WebGuard
from app.web.validation import validate_audio, validate_zip
from app.web.uploads import Uploads


def create_app(settings: Settings | None = None, storage: Path | None = None,
               guard: WebGuard | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    explicit_storage = storage is not None or bool(os.getenv("HEXA_WEB_STORAGE"))
    storage = storage or Path(os.getenv("HEXA_WEB_STORAGE", ".hexa/web"))
    retention = os.getenv("HEXA_WEB_RETENTION_DAYS")
    jobs = Jobs(storage, settings, retention_days=float(retention) if retention else None)
    max_upload = int(os.getenv("HEXA_WEB_MAX_UPLOAD_BYTES", str(2 * 1024**3)))
    guard = guard or WebGuard.from_env(storage, max_upload)
    chunk_root = Path(os.getenv("HEXA_WEB_UPLOAD_ROOT", str(
        storage / "uploads" if explicit_storage else Path.home() / ".hexa" / "uploads")))
    uploads = Uploads(storage, jobs, max_upload, chunk_root,
                      int(os.getenv("HEXA_WEB_CHUNK_BYTES", "262144")))
    if retention:
        uploads.purge_abandoned(float(retention))

    def upload_owner() -> str:
        return hashlib.sha256((guard.token or 'local').encode()).hexdigest()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        # Non-daemon workers finish shutdown before process exit. Cancellation is cooperative.

    app = FastAPI(title="HEXA Web", lifespan=lifespan)
    static = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=static), name="static")

    @app.middleware("http")
    async def guarded(request: Request, call_next):
        refusal = guard.refusal(request)
        response = refusal if refusal is not None else await call_next(request)
        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        return response

    @app.get("/api/session")
    def session(request: Request):
        return {"auth_required": guard.token is not None, "authenticated": guard.authorized(request)}

    @app.post("/api/session")
    def login(request: Request, token: str = Body(..., embed=True)):
        if guard.token is None:
            return {"ok": True, "auth_required": False}
        session_id = guard.login(token)
        client = request.client.host if request.client else "-"
        if session_id is None:
            guard.log.warning("failed login client=%s", client)
            raise HTTPException(401, "Invalid access token")
        guard.log.info("login client=%s", client)
        response = JSONResponse({"ok": True, "auth_required": True})
        response.set_cookie(SESSION_COOKIE, session_id, httponly=True, samesite="strict",
                            secure=request.url.scheme == "https")
        return response

    @app.get("/ready")
    def ready():
        problems = []
        problem = export_root_problem(settings)
        if problem:
            problems.append(f"export_root: {problem}")
        for name, binary in (("ffmpeg", settings.ffmpeg_bin), ("ffprobe", settings.ffprobe_bin)):
            if shutil.which(str(binary)) is None and not Path(str(binary)).is_file():
                problems.append(f"{name}: not found")
        try:
            probe = jobs.root / ".ready"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
        except OSError as exc:
            problems.append(f"storage: {exc}")
        body = {"ready": not problems, "problems": problems, "active_job": (jobs.active() or {}).get("id")}
        return JSONResponse(body, status_code=200 if not problems else 503)

    @app.get("/")
    def index():
        return FileResponse(static / "index.html")

    @app.get("/health")
    def health():
        return {"ok": True}

    def save(upload: UploadFile, path: Path) -> None:
        size = 0
        with path.open("wb") as target:
            while chunk := upload.file.read(1024 * 1024):
                size += len(chunk)
                if size > max_upload:
                    raise HTTPException(413, "Upload exceeds configured size limit")
                target.write(chunk)

    def save_folder(files: list[UploadFile], paths_json: str, path: Path) -> None:
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
                    while chunk := upload.file.read(1024 * 1024):
                        total += len(chunk)
                        if total > max_upload:
                            raise HTTPException(413, "Directory exceeds configured size limit")
                        target.write(chunk)

    @app.post("/api/jobs", status_code=202)
    async def create_job(audio: UploadFile = File(...), package: UploadFile | None = File(None),
                         folder_files: list[UploadFile] | None = File(None),
                         folder_paths: str | None = Form(None)):
        problem = await asyncio.to_thread(export_root_problem, settings)
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
        guard.log.info("job admitted id=%s", job_id)
        directory = jobs.root / job_id
        package_path = directory / "package.zip"
        audio_path = directory / ("narration" + suffix)
        try:
            if package:
                await asyncio.to_thread(save, package, package_path)
            else:
                await asyncio.to_thread(save_folder, folder_files or [], folder_paths or "", package_path)
            await asyncio.to_thread(save, audio, audio_path)
            await asyncio.to_thread(validate_zip, package_path)
            await asyncio.to_thread(validate_audio, audio_path, settings.ffprobe_bin)
            await asyncio.to_thread(FinalPackageLoader().load, package_path, directory / "validation")
            await asyncio.to_thread(shutil.rmtree, directory / "validation", ignore_errors=True)
            jobs.start(job_id, package_path, audio_path)
        except InvalidPackageError as exc:
            jobs.update(job_id, state="failed", message="Input validation failed")
            await asyncio.to_thread(shutil.rmtree, directory, ignore_errors=True)
            raise HTTPException(422, str(exc)) from exc
        except Exception:
            jobs.update(job_id, state="failed", message="Input validation failed")
            await asyncio.to_thread(shutil.rmtree, directory, ignore_errors=True)
            raise
        return {"id": job_id, "state": "queued"}

    @app.get("/api/uploads/config")
    def upload_config():
        return {"chunk_size": uploads.chunk_bytes, "max_file_bytes": max_upload}

    @app.post("/api/uploads", status_code=201)
    async def initialize_upload(request: Request):
        raw = bytearray()
        async for block in request.stream():
            raw.extend(block)
            if len(raw) > 1024 * 1024:
                raise HTTPException(413, "Upload manifest is too large")
        try:
            body = json.loads(raw)
        except (ValueError, UnicodeDecodeError) as exc:
            raise HTTPException(422, "Invalid upload manifest JSON") from exc
        if not isinstance(body, dict):
            raise HTTPException(422, "Invalid upload manifest")
        return await asyncio.to_thread(
            uploads.initialize, upload_owner(), body.get("key"), body.get("manifest", {})
        )

    @app.get("/api/uploads/{upload_id}")
    def upload_status(upload_id: str):
        return uploads.status(upload_id, upload_owner())

    @app.put("/api/uploads/{upload_id}/files/{file_id}/chunks/{index}")
    async def upload_chunk(upload_id: str, file_id: str, index: int, request: Request):
        digest = request.headers.get("x-chunk-sha256", "")
        return await uploads.chunk(upload_id, upload_owner(), file_id, index, digest, request)

    @app.post("/api/uploads/{upload_id}/complete", status_code=202)
    async def finish_upload(upload_id: str):
        result = await asyncio.to_thread(uploads.complete, upload_id, upload_owner(), settings)
        guard.log.info("resumable upload finalized upload=%s job=%s", upload_id, result["id"])
        return result

    @app.delete("/api/uploads/{upload_id}")
    def discard_upload(upload_id: str):
        uploads.discard(upload_id, upload_owner())
        return {"state": "discarded"}

    @app.post("/api/uploads/{upload_id}/retry")
    def retry_upload(upload_id: str):
        return uploads.retry(upload_id, upload_owner())

    @app.get("/api/jobs/active")
    def active_job():
        job = jobs.active()
        if job is None:
            return {"id": None}
        return {key: job[key] for key in ("id", "state", "progress", "stage", "message")}

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
        guard.log.info("job cancel requested id=%s", job_id)
        return {"state": "cancelling"}

    @app.post("/api/jobs/{job_id}/retry", status_code=202)
    def retry_job(job_id: str):
        previous = jobs.get(job_id)
        if previous is None or previous["state"] != "failed":
            raise HTTPException(409, "Only failed jobs can be retried")
        package = Path(previous["package"] or "")
        audio = Path(previous["audio"] or "")
        if not package.is_file() or not audio.is_file():
            raise HTTPException(409, "Saved inputs are unavailable")
        retry_id = jobs.create()
        if retry_id is None:
            raise HTTPException(409, "A generation job is already active")
        jobs.start(retry_id, package, audio)
        return {"id": retry_id, "state": "queued"}

    @app.get("/api/jobs/{job_id}/download/{kind}")
    def download(job_id: str, kind: str):
        job = jobs.get(job_id)
        if kind == "diagnostics":
            if job is None:
                raise HTTPException(404, "Job not found")
            path = jobs.root / job_id / "diagnostics.zip"
            if not path.is_file():
                report = jobs.report(job_id)
                if report is None:
                    raise HTTPException(404, "Diagnostic report unavailable")
                jobs.save_report(job_id, report)
            return FileResponse(path, filename=f"HEXA-diagnostic-{job_id[:8]}.zip")
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
        raise HTTPException(404, "Unknown output")

    return app


app = create_app()
