from __future__ import annotations

import os
import shutil
import json
import zipfile
import asyncio
import hashlib
import hmac
import sqlite3
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Body, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from starlette.background import BackgroundTask
from fastapi.staticfiles import StaticFiles

from app.config import Settings
from app.desktop.export_preflight import export_root_problem
from app.final_package.loader import FinalPackageLoader
from app.shared.errors import InvalidPackageError
from app.web.jobs import Jobs, generation_options
from app.web.intro_zoom import prepare, selection
from app.web.identity import Identity, SESSION_SECONDS
from app.web.admin_data import AdminData
from app.final.bundle import _is_link, export_slug
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
    v2_enabled = os.getenv("HEXA_WEB_V2_ENABLED", "0").lower() in ("1", "true", "yes")
    uploads = Uploads(storage, jobs, max_upload, chunk_root,
                      int(os.getenv("HEXA_WEB_CHUNK_BYTES", "262144")), v2_enabled)
    identity = Identity(jobs.db)
    admin_data = AdminData(jobs.db, settings.export_root)
    if retention:
        uploads.purge_abandoned(float(retention))

    def principal(request: Request) -> dict:
        user = getattr(request.state, "user", None)
        if user is None:
            raise HTTPException(401, "Authentication required")
        return user

    def admin(request: Request) -> dict:
        user = principal(request)
        if user["role"] != "ADMIN":
            raise HTTPException(403, "Administrator access required")
        return user

    def upload_owner(request: Request, upload_id: str | None = None) -> str:
        user = principal(request)
        if upload_id and user["role"] == "ADMIN":
            with uploads.connect() as db:
                row = db.execute("SELECT u.owner FROM uploads u LEFT JOIN users i ON i.id=u.owner WHERE u.id=? AND i.id IS NULL", (upload_id,)).fetchone()
            if row:
                return row["owner"]
        return user["id"]

    def owned_job(request: Request, job_id: str) -> dict:
        job = jobs.get(job_id)
        if job is None or (principal(request)["role"] != "ADMIN" and job.get("user_id") != principal(request)["id"]):
            raise HTTPException(404, "Job not found")
        return job

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        identity.bootstrap()
        admin_data.recover_deletions()
        yield
        # Non-daemon workers finish shutdown before process exit. Cancellation is cooperative.

    app = FastAPI(title="HEXA Web", lifespan=lifespan)
    static = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=static), name="static")

    @app.middleware("http")
    async def guarded(request: Request, call_next):
        refusal = guard.refusal(request)
        path = request.url.path
        public = path in {"/login", "/health", "/ready", "/api/session"} or path.startswith("/static/")
        user = identity.current(request.cookies.get(SESSION_COOKIE))
        request.state.user = user
        if refusal is None and not public and user is None:
            refusal = JSONResponse({"detail": "Authentication required"}, status_code=401) if path.startswith("/api/") else RedirectResponse("/login", status_code=303)
        if refusal is None and user and user["must_change_password"] and path not in {"/change-password", "/api/account/password", "/api/logout", "/api/session"} and not path.startswith("/static/"):
            refusal = JSONResponse({"detail": "Password change required"}, status_code=403) if path.startswith("/api/") else RedirectResponse("/change-password", status_code=303)
        if refusal is None and (path == "/admin" or path.startswith("/api/admin/")) and (not user or user["role"] != "ADMIN"):
            refusal = JSONResponse({"detail": "Administrator access required"}, status_code=403)
        if refusal is None and request.method in {"POST", "PUT", "PATCH", "DELETE"} and not public:
            supplied = request.headers.get("x-csrf-token", "")
            expected = user["csrf_digest"] if user else ""
            if not supplied or not hmac.compare_digest(hashlib.sha256(supplied.encode()).hexdigest(), expected):
                refusal = JSONResponse({"detail": "CSRF token required"}, status_code=403)
        # Root-owned deployment flag, outside the checkout. While it exists,
        # reject new mutations; GET status/downloads stay available.
        # Keeps admitted jobs safe while an upgrade drains live requests.
        if refusal is not None:
            response = refusal
        elif request.method in {"POST", "PUT", "PATCH", "DELETE"} and (jobs.root / ".deploy-maintenance").exists():
            response = JSONResponse({"detail": "HEXA maintenance: retry after deployment"},
                                    status_code=503, headers={"Retry-After": "45"})
        else:
            response = await call_next(request)
        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        if not path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/session")
    def session(request: Request):
        user = getattr(request.state, "user", None)
        return {"auth_required": True, "authenticated": user is not None,
                "user": {"id": user["id"], "email": user["email_normalized"], "role": user["role"], "must_change_password": bool(user["must_change_password"])} if user else None}

    @app.post("/api/session")
    def login(request: Request, email: str = Body(...), password: str = Body(...)):
        client = request.client.host if request.client else "-"
        result = identity.login(email, password, client)
        if result is None:
            raise HTTPException(401, "Invalid credentials")
        session_id, csrf, user = result
        response = JSONResponse({"ok": True, "user": {"id": user["id"], "email": user["email_normalized"], "role": user["role"]}, "csrf": csrf})
        secure_cookie = request.url.scheme == "https"
        response.set_cookie(SESSION_COOKIE, session_id, httponly=True, samesite="strict", secure=secure_cookie, max_age=SESSION_SECONDS, path="/")
        response.set_cookie("hexa_csrf", csrf, httponly=False, samesite="strict", secure=secure_cookie, max_age=SESSION_SECONDS, path="/")
        return response

    @app.post("/api/logout")
    def logout(request: Request):
        identity.revoke(request.cookies.get(SESSION_COOKIE))
        response = JSONResponse({"ok": True})
        response.delete_cookie(SESSION_COOKIE, path="/")
        response.delete_cookie("hexa_csrf", path="/")
        return response

    @app.post("/api/account/password")
    def own_password(request: Request, old_password: str = Body(...), new_password: str = Body(...)):
        try:
            changed = identity.change_own_password(principal(request)["id"], old_password, new_password)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        if not changed:
            raise HTTPException(403, "Current password is incorrect")
        response = JSONResponse({"ok": True, "reauthenticate": True})
        response.delete_cookie(SESSION_COOKIE, path="/")
        response.delete_cookie("hexa_csrf", path="/")
        return response

    @app.get("/api/admin/users")
    def list_users(request: Request, search: str = "", page: int = 1):
        admin(request)
        if not 1 <= page <= 100000 or len(search) > 254:
            raise HTTPException(422, "Invalid search")
        result = identity.users(search, 50, (page - 1) * 50)
        stats = admin_data.user_stats([item["id"] for item in result["items"]])
        for item in result["items"]:
            item["stats"] = stats[item["id"]]
        return result

    @app.post("/api/admin/users", status_code=201)
    def create_user(request: Request, email: str = Body(...), password: str = Body(...), role: str = Body("USER")):
        actor = admin(request)
        try:
            result = identity.create_user(actor["id"], email, password, role)
            admin_data.invalidate_overview()
            return result
        except sqlite3.IntegrityError as exc:
            raise HTTPException(409, "Email already exists") from exc
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.patch("/api/admin/users/{user_id}")
    async def edit_user(user_id: str, request: Request):
        actor = admin(request)
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(422, "Invalid account changes")
        try:
            result = identity.change_user(actor["id"], user_id, body)
            admin_data.invalidate_overview()
            return result
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        except sqlite3.IntegrityError as exc:
            raise HTTPException(409, "Email already exists") from exc
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.get("/api/admin/users/{user_id}/history")
    def admin_user_history(user_id: str, request: Request, page: int = 1):
        admin(request)
        if not 1 <= page <= 100000:
            raise HTTPException(422, "Invalid page")
        if identity.user(user_id) is None:
            raise HTTPException(404, "User not found")
        result = admin_data.history(page=page, user_id=user_id)
        result["stats"] = admin_data.user_stats([user_id])[user_id]
        return result

    @app.get("/api/admin/overview")
    def admin_overview(request: Request, refresh: bool = False):
        admin(request)
        return admin_data.overview(force=refresh)

    @app.get("/api/admin/exports")
    def admin_exports(request: Request, search: str = "", page: int = 1):
        admin(request)
        if not 1 <= page <= 100000 or len(search) > 80:
            raise HTTPException(422, "Invalid search")
        return admin_data.inventory(search, page)

    @app.get("/api/admin/premiere")
    def admin_premiere(request: Request, search: str = "", page: int = 1):
        admin(request)
        if not 1 <= page <= 100000 or len(search) > 80:
            raise HTTPException(422, "Invalid search")
        return admin_data.inventory(search, page, kind="PREMIERE")

    @app.get("/api/admin/premiere/{bundle_id}/download")
    def admin_premiere_download(bundle_id: str, request: Request):
        admin(request)
        return premiere_zip(bundle_id)

    def premiere_zip(bundle_id: str):
        if not admin_data.lease_download(bundle_id):
            raise HTTPException(404, "Premiere project unavailable")
        temporary = None
        try:
            directory, files = admin_data.premiere_files(bundle_id)
            required_bytes = sum(file.stat().st_size for file in files) + 16 * 1024 * 1024
            if shutil.disk_usage(jobs.root).free < required_bytes:
                raise HTTPException(507, "Insufficient space to package Premiere project")
            handle, name = tempfile.mkstemp(prefix="hexa-premiere-", suffix=".zip", dir=jobs.root)
            os.close(handle)
            temporary = Path(name)
            with zipfile.ZipFile(temporary, "w", allowZip64=True, compression=zipfile.ZIP_STORED) as archive:
                for file in files:
                    if _is_link(file) or not file.resolve().is_relative_to(directory):
                        raise LookupError("Premiere project contains an unsafe path")
                    archive.write(file, file.relative_to(directory).as_posix())
        except Exception as exc:
            try:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
            finally:
                admin_data.release_download(bundle_id)
            if isinstance(exc, LookupError):
                raise HTTPException(404, str(exc)) from exc
            raise

        def release_project():
            try:
                temporary.unlink(missing_ok=True)
            finally:
                admin_data.release_download(bundle_id)

        return FileResponse(temporary, filename=f"{directory.parent.name}_{directory.name}_PREMIERE.zip",
                            media_type="application/zip", background=BackgroundTask(release_project))

    @app.get("/api/admin/history")
    def admin_history(request: Request, search: str = "", state: str = "", page: int = 1,
                      from_at: float | None = None, to_at: float | None = None, sort: str = "newest"):
        admin(request)
        if (not 1 <= page <= 100000 or len(search) > 100 or
                state not in {"", "queued", "running", "cancelling", "completed", "failed", "canceled"} or
                sort not in {"newest", "oldest"} or
                (from_at is not None and (from_at < 0 or from_at > 4102444800)) or
                (to_at is not None and (to_at < 0 or to_at > 4102444800)) or
                (from_at is not None and to_at is not None and from_at >= to_at)):
            raise HTTPException(422, "Invalid history filter")
        return admin_data.history(search, state, page, from_at, to_at, sort)

    @app.delete("/api/admin/exports/{bundle_id}")
    def delete_export(bundle_id: str, request: Request):
        actor = admin(request)
        try:
            return admin_data.delete_bundle(bundle_id, actor["id"])
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.get("/api/admin/exports/{bundle_id}/download/{kind}")
    def admin_export_download(bundle_id: str, kind: str, request: Request):
        admin(request)
        if not admin_data.secure_root() or admin_data.root is None:
            raise HTTPException(404, "Export root is not configured")
        if kind not in {"youtube", "reels"}:
            raise HTTPException(404, "Unknown output")
        with admin_data.connect() as db:
            row = db.execute("SELECT slug,version FROM export_inventory WHERE id=? AND kind='VIDEO' AND status='AVAILABLE'", (bundle_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Export unavailable")
        directory = admin_data.root / row["slug"] / f"v{row['version']}"
        path = directory / f"{row['slug']}_{kind.upper()}.mp4"
        if (_is_link(admin_data.configured_root) or _is_link(admin_data.root) or _is_link(directory.parent) or _is_link(directory) or _is_link(path) or
                not path.is_file() or path.resolve().parent != directory.resolve()):
            raise HTTPException(404, "Output unavailable")
        if not admin_data.lease_download(bundle_id):
            raise HTTPException(404, "Output unavailable")
        return FileResponse(path, filename=path.name, media_type="video/mp4", background=BackgroundTask(admin_data.release_download, bundle_id))

    @app.get("/ready")
    def ready(request: Request):
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
        active = (jobs.active() or {}).get("id")
        user = getattr(request.state, "user", None)
        if user and user["role"] == "ADMIN":
            body = {"ready": not problems, "problems": problems, "active_job": active}
        else:
            body = {"ready": not problems, "active_job": True if active else None}
        return JSONResponse(body, status_code=200 if not problems else 503)

    @app.get("/")
    def index():
        return FileResponse(static / "index.html")

    @app.get("/login")
    def login_page():
        return FileResponse(static / "login.html")

    @app.get("/change-password")
    def change_password_page():
        return FileResponse(static / "change-password.html")

    @app.get("/admin")
    def admin_page(request: Request):
        admin(request)
        return FileResponse(static / "admin.html")

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
    async def create_job(request: Request, audio: UploadFile = File(...), package: UploadFile | None = File(None),
                         folder_files: list[UploadFile] | None = File(None),
                         folder_paths: str | None = Form(None), sound_effects: str | None = Form(None),
                         background_music: str | None = Form(None), output_kind: str = Form("VIDEO"),
                         intro_image: UploadFile | None = File(None),
                         intro_voice: UploadFile | None = File(None),
                         intro_focus_x: float | None = Form(None),
                         intro_focus_y: float | None = Form(None),
                         intro_magnification: float | None = Form(None)):
        options = {key: value.strip().lower() in {"1", "true", "on", "yes"}
                   for key, value in (("sound_effects", sound_effects), ("background_music", background_music))
                   if value is not None}
        options["output_kind"] = output_kind
        wants_intro = any(value is not None for value in (intro_image, intro_voice,
                       intro_focus_x, intro_focus_y, intro_magnification))
        if wants_intro:
            if intro_image is None or intro_voice is None or any(value is None for value in
                   (intro_focus_x, intro_focus_y, intro_magnification)):
                raise HTTPException(422, "Intro Zoom requires image, voice and target")
            try:
                options["intro_zoom"] = selection({"focus_x": intro_focus_x,
                    "focus_y": intro_focus_y, "magnification": intro_magnification})
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
        try:
            generation_options(options)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
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
        try:
            job_id = jobs.create(principal(request)["id"])
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc
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
            if wants_intro and intro_image is not None and intro_voice is not None:
                image_suffix = Path(intro_image.filename or "").suffix.lower()
                voice_suffix = Path(intro_voice.filename or "").suffix.lower()
                image_temp = directory / ("upload-image" + image_suffix)
                voice_temp = directory / ("upload-voice" + voice_suffix)
                await asyncio.to_thread(save, intro_image, image_temp)
                await asyncio.to_thread(save, intro_voice, voice_temp)
                try:
                    await asyncio.to_thread(prepare, directory, image_temp, voice_temp,
                        options["intro_zoom"], ffprobe_bin=settings.ffprobe_bin,
                        ffmpeg_bin=settings.ffmpeg_bin)
                except ValueError as exc:
                    raise HTTPException(422, str(exc)) from exc
                finally:
                    image_temp.unlink(missing_ok=True)
                    voice_temp.unlink(missing_ok=True)
            await asyncio.to_thread(validate_zip, package_path)
            await asyncio.to_thread(validate_audio, audio_path, settings.ffprobe_bin)
            validated_package = await asyncio.to_thread(FinalPackageLoader().load, package_path, directory / "validation")
            if validated_package is not None:
                jobs.update(job_id, package_name=export_slug(validated_package.project_slug or validated_package.package_id))
            await asyncio.to_thread(shutil.rmtree, directory / "validation", ignore_errors=True)
            jobs.start(job_id, package_path, audio_path, options)
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
        return {"chunk_size": uploads.chunk_bytes, "max_file_bytes": max_upload,
                "protocols": [1, 2] if uploads.v2_enabled else [1],
                "v2_chunk_size": 4 * 1024 * 1024,
                # the soundtrack switches' defaults (hexa.settings.json / environment)
                "sound_effects": settings.sound_effects, "background_music": settings.background_music}

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
            uploads.initialize, upload_owner(request), body.get("key"), body.get("manifest", {})
        )

    @app.get("/api/uploads/{upload_id}")
    def upload_status(upload_id: str, request: Request):
        return uploads.status(upload_id, upload_owner(request, upload_id))

    @app.put("/api/uploads/{upload_id}/files/{file_id}/chunks/{index}")
    async def upload_chunk(upload_id: str, file_id: str, index: int, request: Request):
        digest = request.headers.get("x-chunk-sha256", "")
        return await uploads.chunk(upload_id, upload_owner(request, upload_id), file_id, index, digest, request)

    @app.post("/api/uploads/{upload_id}/complete", status_code=202)
    async def finish_upload(upload_id: str, request: Request):
        try:
            body = json.loads(await request.body() or b"{}")
        except (ValueError, UnicodeDecodeError) as exc:
            raise HTTPException(422, "Invalid completion options") from exc
        try:
            options = generation_options(body)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        result = await asyncio.to_thread(uploads.complete, upload_id, upload_owner(request, upload_id), settings,
                                         options)
        guard.log.info("resumable upload finalized upload=%s job=%s", upload_id, result["id"])
        return result

    @app.delete("/api/uploads/{upload_id}")
    def discard_upload(upload_id: str, request: Request):
        uploads.discard(upload_id, upload_owner(request, upload_id))
        return {"state": "discarded"}

    @app.post("/api/uploads/{upload_id}/retry")
    def retry_upload(upload_id: str, request: Request):
        return uploads.retry(upload_id, upload_owner(request, upload_id))

    @app.get("/api/jobs/active")
    def active_job(request: Request):
        job = jobs.active()
        if job is None or (principal(request)["role"] != "ADMIN" and job.get("user_id") != principal(request)["id"]):
            return {"id": None}
        return {key: job[key] for key in ("id", "state", "progress", "stage", "message")}

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str, request: Request):
        job = owned_job(request, job_id)
        result = {key: job[key] for key in ("id", "state", "progress", "stage", "message")}
        result["output_kind"] = jobs.options_for(job_id).get("output_kind", "VIDEO")
        return result

    @app.get("/api/jobs/{job_id}/events")
    def events(job_id: str, request: Request):
        owned_job(request, job_id)
        return jobs.events(job_id)

    @app.post("/api/jobs/{job_id}/cancel")
    def cancel(job_id: str, request: Request):
        owned_job(request, job_id)
        if not jobs.cancel(job_id):
            raise HTTPException(409, "Job is not active")
        guard.log.info("job cancel requested id=%s", job_id)
        return {"state": "cancelling"}

    @app.post("/api/jobs/{job_id}/retry", status_code=202)
    def retry_job(job_id: str, request: Request):
        previous = owned_job(request, job_id)
        if previous is None or previous["state"] != "failed":
            raise HTTPException(409, "Only failed jobs can be retried")
        package = Path(previous["package"] or "")
        audio = Path(previous["audio"] or "")
        if not package.is_file() or not audio.is_file():
            raise HTTPException(409, "Saved inputs are unavailable")
        try:
            retry_id = jobs.create(principal(request)["id"], package_name=previous.get("package_name"))
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc
        if retry_id is None:
            raise HTTPException(409, "A generation job is already active")
        jobs.start(retry_id, package, audio, jobs.options_for(job_id))
        return {"id": retry_id, "state": "queued"}

    @app.get("/api/jobs/{job_id}/download/{kind}")
    def download(job_id: str, kind: str, request: Request):
        job = owned_job(request, job_id)
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
        if kind == "premiere":
            if jobs.options_for(job_id).get("output_kind") != "PREMIERE":
                raise HTTPException(404, "Premiere project unavailable")
            if not admin_data.secure_root() or admin_data.root is None or admin_data.root not in bundle.parents:
                raise HTTPException(404, "Premiere project unavailable")
            return premiere_zip(f"{bundle.parent.name}:{bundle.name}")
        if kind in {"youtube", "reels", "manifest"}:
            if jobs.options_for(job_id).get("output_kind") == "PREMIERE" and kind != "manifest":
                raise HTTPException(404, "Video output unavailable")
            if not admin_data.secure_root() or admin_data.root is None or admin_data.root not in bundle.parents:
                raise HTTPException(404, "Output unavailable")
            path = bundle / "export.json" if kind == "manifest" else Path(job[kind]).resolve()
            suffix = ".json" if kind == "manifest" else ".mp4"
            if (path.parent != bundle or path.suffix.lower() != suffix or
                    (kind == "manifest" and path.name != "export.json") or
                    not path.is_file() or _is_link(path)):
                raise HTTPException(404, "Output unavailable")
            bundle_id = f"{bundle.parent.name}:{bundle.name}"
            if not admin_data.lease_download(bundle_id):
                raise HTTPException(404, "Output unavailable")
            return FileResponse(
                path, filename=path.name,
                media_type="application/json" if kind == "manifest" else "video/mp4",
                background=BackgroundTask(admin_data.release_download, bundle_id),
            )
        raise HTTPException(404, "Unknown output")

    return app


app = create_app()
