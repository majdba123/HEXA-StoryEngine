from __future__ import annotations

import hashlib
import errno
import asyncio
import json
import os
import re
import shutil
import sqlite3
import threading
import time
import uuid
import zipfile
from pathlib import Path
from fastapi import HTTPException, Request
from app.web.validation import validate_zip, validate_audio
from app.final_package.loader import FinalPackageLoader
from app.final.bundle import export_slug
from app.desktop.export_preflight import export_root_problem
from app.shared.errors import InvalidPackageError
from app.web.intro_zoom import IMAGE_LIMIT, VOICE_LIMIT, selection, prepare

SHA = re.compile(r"^[0-9a-f]{64}$")
AUDIO = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg"}
CHUNK = 256 * 1024
V2_CHUNK = 4 * 1024 * 1024


def safe_path(name: str) -> bool:
    return (
        isinstance(name, str)
        and 0 < len(name) <= 512
        and "\\" not in name
        and not name.startswith("/")
        and ":" not in name
        and all(ord(char) >= 32 for char in name)
        and all(part not in ("", ".", "..") for part in name.split("/"))
    )


class Uploads:
    def __init__(
        self,
        root: Path,
        jobs,
        max_bytes: int,
        chunk_root: Path | None = None,
        chunk_bytes: int = CHUNK,
        v2_enabled: bool = False,
    ):
        if chunk_bytes not in (CHUNK, 2 * CHUNK, 4 * CHUNK):
            raise ValueError("HEXA_WEB_CHUNK_BYTES must be 262144, 524288, or 1048576")
        self.chunk_bytes = chunk_bytes
        self.v2_enabled = v2_enabled
        self.root = (chunk_root or root / "uploads").resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if os.name == "posix":
            self.root.chmod(0o700)
        self.db = jobs.db
        self.jobs = jobs
        self.max_bytes = max_bytes
        self.max_reserved = int(os.getenv("HEXA_WEB_TOTAL_UPLOAD_BYTES", str(2 * max_bytes)))
        self.lock = threading.RLock()
        with self.connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS uploads (id TEXT PRIMARY KEY, owner TEXT NOT NULL, key TEXT NOT NULL, state TEXT NOT NULL, manifest TEXT NOT NULL, job_id TEXT, error TEXT, created REAL, updated REAL NOT NULL, validator_pid INTEGER, verify_seconds REAL, validation_seconds REAL, admitted_at REAL, expected_bytes INTEGER, UNIQUE(owner,key))"
            )
            db.execute("CREATE INDEX IF NOT EXISTS uploads_job_id ON uploads(job_id)")
            db.execute(
                "CREATE TABLE IF NOT EXISTS upload_files (upload_id TEXT NOT NULL, file_id TEXT NOT NULL, offset INTEGER NOT NULL DEFAULT 0, sha256 TEXT, PRIMARY KEY(upload_id,file_id))"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS upload_create_events (owner TEXT NOT NULL, created REAL NOT NULL)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS upload_chunks (upload_id TEXT NOT NULL, file_id TEXT NOT NULL, chunk_index INTEGER NOT NULL, sha256 TEXT NOT NULL, size INTEGER NOT NULL, PRIMARY KEY(upload_id,file_id,chunk_index))"
            )
            columns = {row["name"] for row in db.execute("PRAGMA table_info(upload_files)")}
            if "sha256" not in columns:
                db.execute("ALTER TABLE upload_files ADD COLUMN sha256 TEXT")
            upload_columns = {row["name"] for row in db.execute("PRAGMA table_info(uploads)")}
            if "created" not in upload_columns:
                db.execute("ALTER TABLE uploads ADD COLUMN created REAL")
                db.execute("UPDATE uploads SET created=updated WHERE created IS NULL")
            if "validator_pid" not in upload_columns:
                db.execute("ALTER TABLE uploads ADD COLUMN validator_pid INTEGER")
            for column in ("verify_seconds", "validation_seconds", "admitted_at"):
                if column not in upload_columns:
                    db.execute(f"ALTER TABLE uploads ADD COLUMN {column} REAL")
            if "expected_bytes" not in upload_columns:
                db.execute("ALTER TABLE uploads ADD COLUMN expected_bytes INTEGER")
                for row in db.execute("SELECT id,manifest FROM uploads"):
                    manifest = json.loads(row["manifest"])
                    expected = sum(file["size"] for file in manifest["files"])
                    db.execute(
                        "UPDATE uploads SET expected_bytes=? WHERE id=?", (expected, row["id"])
                    )
            for row in db.execute("SELECT id,validator_pid FROM uploads WHERE state='validating'"):
                if not self.pid_alive(row["validator_pid"]):
                    db.execute(
                        "UPDATE uploads SET state='uploading',validator_pid=NULL WHERE id=?",
                        (row["id"],),
                    )

    @staticmethod
    def pid_alive(pid: int | None) -> bool:
        if not pid:
            return False
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    def connect(self):
        db = sqlite3.connect(self.db, timeout=30)
        db.row_factory = sqlite3.Row
        return db

    def initialize(self, owner: str, key: str, manifest: dict):
        if not isinstance(manifest, dict):
            raise HTTPException(422, "Invalid upload manifest")
        if not isinstance(key, str) or not 8 <= len(key) <= 128:
            raise HTTPException(422, "Invalid idempotency key")
        # An old session keeps its stored chunk size even when the server default changes.
        with self.connect() as db:
            old = db.execute(
                "SELECT id,manifest FROM uploads WHERE owner=? AND key=?", (owner, key)
            ).fetchone()
        if old:
            existing = json.loads(old["manifest"])
            incoming = {**manifest, "chunk_size": manifest.get("chunk_size", existing["chunk_size"])}
            if incoming != existing:
                raise HTTPException(409, "Idempotency key conflicts with another manifest")
            return self.status(old["id"], owner)
        protocol = manifest.get("protocol", 1)
        if type(protocol) is not int or protocol not in (1, 2):
            raise HTTPException(422, "Unsupported upload protocol")
        if protocol == 2 and not self.v2_enabled:
            raise HTTPException(409, "Upload protocol V2 is disabled for new sessions")
        chunk_size = manifest.get("chunk_size", self.chunk_bytes)
        if type(chunk_size) is not int or chunk_size not in (
            (self.chunk_bytes,) if protocol == 1 else (4 * CHUNK, 8 * CHUNK, V2_CHUNK)
        ):
            raise HTTPException(409, "Unsupported chunk size for upload protocol")
        manifest = {**manifest, "chunk_size": chunk_size}
        files = manifest.get("files")
        mode = manifest.get("mode")
        if (
            mode not in ("zip", "folder")
            or not isinstance(files, list)
            or not 2 <= len(files) <= 5001
        ):
            raise HTTPException(422, "Invalid upload manifest")
        ids, paths, total, package, audio = set(), set(), 0, 0, 0
        intros = {"intro_image": 0, "intro_audio": 0}
        for file in files:
            if not isinstance(file, dict) or set(file) != {
                "id",
                "path",
                "size",
                "fingerprint",
                "role",
            }:
                raise HTTPException(422, "Invalid file entry")
            fid, path, size, digest, role = (
                file[k] for k in ("id", "path", "size", "fingerprint", "role")
            )
            if (
                not isinstance(fid, str)
                or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", fid)
                or fid in ids
                or not safe_path(path)
                or path.casefold() in paths
                or type(size) is not int
                or size < 0
                or size > self.max_bytes
                or not isinstance(digest, str)
                or not SHA.fullmatch(digest)
                or role not in ("package", "audio", "intro_image", "intro_audio")
            ):
                raise HTTPException(422, "Invalid file entry")
            ids.add(fid)
            paths.add(path.casefold())
            total += size
            package += role == "package"
            audio += role == "audio"
            if role in intros:
                intros[role] += 1
                allowed = {".png", ".jpg", ".jpeg", ".webp"} if role == "intro_image" else AUDIO
                limit = IMAGE_LIMIT if role == "intro_image" else VOICE_LIMIT
                if "/" in path or Path(path).suffix.lower() not in allowed or not 0 < size <= limit:
                    raise HTTPException(422, "Invalid Intro Zoom file")
            if role == "audio" and ("/" in path or Path(path).suffix.lower() not in AUDIO):
                raise HTTPException(422, "Unsupported audio path")
            if size == 0 and (role == "audio" or mode == "zip"):
                raise HTTPException(422, "ZIP and narration must not be empty")
            if (
                mode == "zip"
                and role == "package"
                and ("/" in path or not path.lower().endswith(".zip"))
            ):
                raise HTTPException(422, "Package must be a ZIP")
            if mode == "folder" and role == "package" and "/" not in path:
                raise HTTPException(422, "Folder path required")
        if (
            audio != 1
            or package != (1 if mode == "zip" else len(files) - 1 - sum(intros.values()))
            or total > 2 * self.max_bytes
            or intros["intro_image"] != intros["intro_audio"]
            or intros["intro_image"] > 1
            or ("intro_zoom" in manifest) != bool(intros["intro_image"])
        ):
            raise HTTPException(413, "Upload exceeds limit or has invalid roles")
        if intros["intro_image"]:
            try:
                selection(manifest["intro_zoom"])
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
        canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":"))
        with self.lock, self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute(
                "SELECT * FROM uploads WHERE owner=? AND key=?", (owner, key)
            ).fetchone()
            if old:
                if old["manifest"] != canonical:
                    raise HTTPException(409, "Idempotency key conflicts with another manifest")
                return self.status(old["id"], owner)
            now = time.time()
            db.execute("DELETE FROM upload_create_events WHERE created<?", (now - 60,))
            recent = db.execute(
                "SELECT COUNT(*) FROM upload_create_events WHERE owner=?", (owner,)
            ).fetchone()[0]
            if recent >= 10:
                raise HTTPException(429, "Upload creation rate limit exceeded")
            reserved = db.execute(
                "SELECT COALESCE(SUM(expected_bytes),0) FROM uploads WHERE job_id IS NULL"
            ).fetchone()[0]
            if reserved + total > self.max_reserved:
                raise HTTPException(429, "Upload storage reservation limit exceeded")
            if sum(1 for p in self.root.iterdir() if p.is_dir()) >= 100:
                raise HTTPException(429, "Too many upload sessions")
            if shutil.disk_usage(self.root).free < 2 * total + 64 * 1024 * 1024:
                raise HTTPException(507, "Insufficient storage")
            uid = uuid.uuid4().hex
            (self.root / uid).mkdir(mode=0o700)
            db.execute(
                "INSERT INTO uploads(id,owner,key,state,manifest,job_id,error,created,updated,expected_bytes) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (uid, owner, key, "uploading", canonical, None, None, now, now, total),
            )
            db.execute("INSERT INTO upload_create_events VALUES(?,?)", (owner, now))
            db.executemany(
                "INSERT INTO upload_files(upload_id,file_id) VALUES(?,?)",
                [(uid, f["id"]) for f in files],
            )
            db.commit()
            return self.status(uid, owner)

    def status(self, uid: str, owner: str):
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM uploads WHERE id=? AND owner=?", (uid, owner)
            ).fetchone()
            if row is None:
                raise HTTPException(404, "Upload not found")
            records = list(db.execute("SELECT * FROM upload_files WHERE upload_id=?", (uid,)))
            offsets = {r["file_id"]: r["offset"] for r in records}
            hashes = {r["file_id"]: r["sha256"] for r in records if r["sha256"]}
        manifest = json.loads(row["manifest"])
        return {
            "id": uid,
            "state": row["state"],
            "files": offsets,
            "sha256": hashes,
            "manifest": manifest,
            "job_id": row["job_id"],
            "error": row["error"],
            "created": row["created"],
            "updated": row["updated"],
            "verify_seconds": row["verify_seconds"],
            "validation_seconds": row["validation_seconds"],
            "admitted_at": row["admitted_at"],
            "chunk_size": manifest.get("chunk_size", CHUNK),
        }

    async def chunk(
        self, uid: str, owner: str, fid: str, index: int, digest: str, request: Request
    ):
        if index < 0 or not SHA.fullmatch(digest):
            raise HTTPException(422, "Invalid chunk index or digest")
        # Bound request bodies even when Content-Length is absent.
        data = bytearray()
        async for block in request.stream():
            data.extend(block)
            if len(data) > V2_CHUNK:
                raise HTTPException(413, "Chunk too large")
        if not data or hashlib.sha256(data).hexdigest() != digest:
            raise HTTPException(422, "Chunk checksum mismatch")
        # Keep request streaming async; move fsync and SQLite commits off the event loop.
        return await asyncio.to_thread(
            self._commit_chunk, uid, owner, fid, index, digest, bytes(data)
        )

    def _commit_chunk(
        self, uid: str, owner: str, fid: str, index: int, digest: str, data: bytes
    ):
        with self.lock, self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            state = self.status(uid, owner)
            if state["state"] != "uploading":
                raise HTTPException(409, "Upload is not accepting chunks")
            chunk_size = state["chunk_size"]
            if len(data) > chunk_size or index > self.max_bytes // chunk_size:
                raise HTTPException(413, "Chunk exceeds configured size")
            file = next((f for f in state["manifest"]["files"] if f["id"] == fid), None)
            if file is None:
                raise HTTPException(404, "File not found")
            offset = index * chunk_size
            expected = min(chunk_size, file["size"] - offset)
            if expected <= 0 or len(data) != expected:
                raise HTTPException(422, "Chunk length mismatch")
            path = self.root / uid / fid
            committed = state["files"][fid]
            if offset < committed:
                with path.open("rb") as stream:
                    stream.seek(offset)
                    if hashlib.sha256(stream.read(expected)).hexdigest() != digest:
                        raise HTTPException(409, "Conflicting duplicate chunk")
                return self.status(uid, owner)
            if offset != committed:
                raise HTTPException(409, "Expected next chunk at committed offset")
            # A crash between append and DB commit is reconciled by truncating to the DB offset.
            try:
                with path.open("r+b" if path.exists() else "w+b") as stream:
                    if os.name == "posix":
                        path.chmod(0o600)
                    stream.truncate(committed)
                    stream.seek(committed)
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
            except OSError as exc:
                if exc.errno in (errno.ENOSPC, errno.EDQUOT):
                    raise HTTPException(507, "Insufficient storage for chunk") from exc
                raise
            db.execute(
                "UPDATE upload_files SET offset=? WHERE upload_id=? AND file_id=?",
                (committed + expected, uid, fid),
            )
            db.execute(
                "INSERT INTO upload_chunks(upload_id,file_id,chunk_index,sha256,size) VALUES(?,?,?,?,?)",
                (uid, fid, index, digest, expected),
            )
            db.execute("UPDATE uploads SET updated=? WHERE id=?", (time.time(), uid))
            db.commit()
            return self.status(uid, owner)

    def fail(self, uid: str, message: str):
        with self.connect() as db:
            db.execute(
                "UPDATE uploads SET state='failed',validator_pid=NULL,error=?,updated=? WHERE id=?",
                (message[:1000], time.time(), uid),
            )

    def discard(self, uid: str, owner: str):
        with self.lock:
            state = self.status(uid, owner)
            if state["job_id"]:
                raise HTTPException(409, "Generation job already admitted")
            if state["state"] == "validating":
                raise HTTPException(409, "Cannot discard while validation is in progress")
            if (self.root / uid).exists():
                shutil.rmtree(self.root / uid)
            with self.connect() as db:
                db.execute("DELETE FROM upload_chunks WHERE upload_id=?", (uid,))
                db.execute("DELETE FROM upload_files WHERE upload_id=?", (uid,))
                db.execute("DELETE FROM uploads WHERE id=?", (uid,))

    def retry(self, uid: str, owner: str):
        with self.lock:
            state = self.status(uid, owner)
            if state["state"] != "failed" or state["job_id"]:
                raise HTTPException(409, "Upload is not retryable")
            with self.connect() as db:
                db.execute(
                    "UPDATE uploads SET state='uploading',validator_pid=NULL,error=NULL,updated=? WHERE id=?",
                    (time.time(), uid),
                )
            return self.status(uid, owner)

    def purge_abandoned(self, days: float):
        cutoff = time.time() - days * 86400
        removed = 0
        with self.lock, self.connect() as db:
            rows = db.execute(
                "SELECT u.id FROM uploads u LEFT JOIN jobs j ON j.id=u.job_id "
                "WHERE u.updated<? AND ((u.job_id IS NULL AND u.state IN ('uploading','failed')) "
                "OR (u.job_id IS NOT NULL AND j.state IN ('completed','failed','canceled')))",
                (cutoff,),
            ).fetchall()
            for row in rows:
                uid = row["id"]
                try:
                    shutil.rmtree(self.root / uid)
                except FileNotFoundError:
                    pass
                except OSError:
                    continue
                db.execute("DELETE FROM upload_files WHERE upload_id=?", (uid,))
                db.execute("DELETE FROM upload_chunks WHERE upload_id=?", (uid,))
                db.execute("DELETE FROM uploads WHERE id=?", (uid,))
                removed += 1
        return removed

    def complete(self, uid, owner, settings, options: dict | None = None):
        with self.lock:
            state = self.status(uid, owner)
            if state["job_id"]:
                return {"id": state["job_id"], "state": "queued"}
            if state["state"] != "uploading":
                raise HTTPException(409, "Upload cannot be finalized")
            files = state["manifest"]["files"]
            if any(state["files"][f["id"]] != f["size"] for f in files):
                raise HTTPException(409, "Upload is incomplete")
            with self.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                row = db.execute("SELECT state,job_id FROM uploads WHERE id=?", (uid,)).fetchone()
                if row["job_id"]:
                    return {"id": row["job_id"], "state": "queued"}
                if row["state"] != "uploading":
                    raise HTTPException(409, "Upload is already validating")
                db.execute(
                    "UPDATE uploads SET state='validating',validator_pid=?,updated=? WHERE id=?",
                    (os.getpid(), time.time(), uid),
                )
        validation_started = None
        try:
            problem = export_root_problem(settings)
            if problem:
                raise HTTPException(422, problem)
            verification_started = time.perf_counter()
            for f in files:
                digest = hashlib.sha256()
                file_digest = hashlib.sha256()
                with (self.root / uid / f["id"]).open("rb") as stream:
                    while block := stream.read(state["chunk_size"]):
                        digest.update(hashlib.sha256(block).hexdigest().encode("ascii"))
                        file_digest.update(block)
                if digest.hexdigest() != f["fingerprint"]:
                    raise HTTPException(422, f"File integrity mismatch: {f['path']}")
                with self.connect() as db:
                    db.execute(
                        "UPDATE upload_files SET sha256=? WHERE upload_id=? AND file_id=?",
                        (file_digest.hexdigest(), uid, f["id"]),
                    )
            with self.connect() as db:
                db.execute(
                    "UPDATE uploads SET verify_seconds=? WHERE id=?",
                    (time.perf_counter() - verification_started, uid),
                )
            validation_started = time.perf_counter()
            audio = next(f for f in files if f["role"] == "audio")
            audio_path = self.root / uid / audio["id"]
            # The stored identifier has no extension; probe the content with its validated suffix.
            audio_named = self.root / uid / ("narration" + Path(audio["path"]).suffix.lower())
            shutil.copyfile(audio_path, audio_named)
            if os.name == "posix":
                audio_named.chmod(0o600)
            validate_audio(audio_named, settings.ffprobe_bin)
            if "intro_zoom" in state["manifest"]:
                if (options or {}).get("output_kind", "VIDEO") != "VIDEO":
                    raise HTTPException(422, "Intro Zoom supports MP4 video only, not Premiere")
                image_entry = next(f for f in files if f["role"] == "intro_image")
                voice_entry = next(f for f in files if f["role"] == "intro_audio")
                image_input = self.root / uid / ("pending-image" + Path(image_entry["path"]).suffix.lower())
                voice_input = self.root / uid / ("pending-voice" + Path(voice_entry["path"]).suffix.lower())
                try:
                    shutil.copyfile(self.root / uid / image_entry["id"], image_input)
                    shutil.copyfile(self.root / uid / voice_entry["id"], voice_input)
                    prepare(self.root / uid, image_input, voice_input,
                            state["manifest"]["intro_zoom"],
                            ffprobe_bin=settings.ffprobe_bin, ffmpeg_bin=settings.ffmpeg_bin)
                except ValueError as exc:
                    raise HTTPException(422, str(exc)) from exc
                finally:
                    image_input.unlink(missing_ok=True)
                    voice_input.unlink(missing_ok=True)
            package_path = self.root / uid / "package.zip"
            if state["manifest"]["mode"] == "zip":
                package = next(f for f in files if f["role"] == "package")
                shutil.copyfile(self.root / uid / package["id"], package_path)
            else:
                with zipfile.ZipFile(
                    package_path, "w", compression=zipfile.ZIP_STORED
                ) as archive:
                    for f in files:
                        if f["role"] == "package":
                            archive.write(self.root / uid / f["id"], f["path"])
            if os.name == "posix":
                package_path.chmod(0o600)
            validate_zip(package_path)
            validation = self.root / uid / "validation"
            try:
                validated_package = FinalPackageLoader().load(package_path, validation)
            except InvalidPackageError as exc:
                raise HTTPException(422, str(exc)) from exc
            finally:
                shutil.rmtree(validation, ignore_errors=True)
            with self.connect() as db:
                db.execute(
                    "UPDATE uploads SET validation_seconds=? WHERE id=?",
                    (time.perf_counter() - validation_started, uid),
                )
            # The jobs unique index and upload association commit in the same SQLite transaction.
            job_id = uuid.uuid4().hex
            with self.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                row = db.execute("SELECT job_id FROM uploads WHERE id=?", (uid,)).fetchone()
                if row["job_id"]:
                    return {"id": row["job_id"], "state": "queued"}
                if len(owner) == 32 and all(char in "0123456789abcdef" for char in owner):
                    if not db.execute("SELECT 1 FROM users WHERE id=? AND is_active=1 AND must_change_password=0 AND deleted_at IS NULL", (owner,)).fetchone():
                        raise HTTPException(403, "Account is no longer active")
                try:
                    db.execute(
                        "INSERT INTO jobs(id,state,message,package,audio,user_id,created_at,package_name) VALUES(?,'queued','Queued',?,?,?,?,?)",
                        (job_id, str(package_path), str(audio_named), owner, time.time(),
                         export_slug(validated_package.project_slug or validated_package.package_id) if validated_package is not None else None),
                    )
                    db.execute(
                        "INSERT INTO owners(job_id,pid) VALUES(?,?)", (job_id, os.getpid())
                    )
                except sqlite3.IntegrityError as exc:
                    raise HTTPException(409, "A generation job is already active") from exc
                db.execute(
                    "UPDATE uploads SET state='queued',validator_pid=NULL,job_id=?,admitted_at=?,updated=? WHERE id=?",
                    (job_id, time.time(), time.time(), uid),
                )
            (self.jobs.root / job_id).mkdir(exist_ok=True)
            job_options = dict(options or {})
            if "intro_zoom" in state["manifest"]:
                job_options["intro_zoom"] = selection(state["manifest"]["intro_zoom"])
            self.jobs.start(job_id, package_path, audio_named, job_options)
            return {"id": job_id, "state": "queued"}
        except HTTPException as exc:
            if validation_started is not None:
                with self.connect() as db:
                    db.execute(
                        "UPDATE uploads SET validation_seconds=? WHERE id=?",
                        (time.perf_counter() - validation_started, uid),
                    )
            if exc.status_code == 409:
                with self.connect() as db:
                    db.execute(
                        "UPDATE uploads SET state='uploading',validator_pid=NULL,error=?,updated=? WHERE id=? AND job_id IS NULL",
                        (str(exc.detail), time.time(), uid),
                    )
            else:
                self.fail(uid, str(exc.detail))
            raise
        except OSError as exc:
            if validation_started is not None:
                with self.connect() as db:
                    db.execute(
                        "UPDATE uploads SET validation_seconds=? WHERE id=?",
                        (time.perf_counter() - validation_started, uid),
                    )
            self.fail(uid, str(exc))
            if exc.errno in (errno.ENOSPC, errno.EDQUOT):
                raise HTTPException(507, "Insufficient storage during validation") from exc
            raise
        except Exception as exc:
            if validation_started is not None:
                with self.connect() as db:
                    db.execute(
                        "UPDATE uploads SET validation_seconds=? WHERE id=?",
                        (time.perf_counter() - validation_started, uid),
                    )
            self.fail(uid, str(exc))
            raise
