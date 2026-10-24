from __future__ import annotations

import json
import shutil
import sqlite3
import threading
import time
import uuid
import os
from dataclasses import replace
from pathlib import Path

from app.config import Settings
from app.diagnostics import BuildReportSession
from app.pipeline import StoryEnginePipeline
from app.shared.errors import GenerationCancelledError


# The operator's soundtrack switches a job may carry (web form / upload completion).
SOUND_OPTIONS = ("sound_effects", "background_music")
OPTIONS_FILE = "options.json"


def _process_alive(pid: int) -> bool:
    if os.name == "nt":
        # os.kill(pid, 0) sends a console control event on Windows.
        import ctypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = (ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong)
        kernel.OpenProcess.restype = ctypes.c_void_p
        kernel.GetExitCodeProcess.argtypes = (ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong))
        kernel.CloseHandle.argtypes = (ctypes.c_void_p,)
        handle = kernel.OpenProcess(0x1000, 0, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            return bool(kernel.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def sound_options(raw: object) -> dict[str, bool]:
    """Only the known switches with real booleans; anything else keeps the server default."""
    if not isinstance(raw, dict):
        return {}
    return {key: raw[key] for key in SOUND_OPTIONS if isinstance(raw.get(key), bool)}


def generation_options(raw: object) -> dict:
    """Keep the output choice with the sound switches across retries."""
    chosen = sound_options(raw)
    if isinstance(raw, dict) and "output_kind" in raw:
        if raw["output_kind"] not in {"VIDEO", "PREMIERE"}:
            raise ValueError("Invalid output kind")
        chosen["output_kind"] = raw["output_kind"]
    return chosen


class Jobs:
    """One worker per server process; SQLite admission also excludes other processes."""

    def __init__(self, root: Path, settings: Settings, *, retention_days: float | None = None) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.settings = settings
        self.db = self.root / "jobs.sqlite3"
        self._lock = threading.Lock()
        self._report_lock = threading.Lock()
        self._cancel: dict[str, threading.Event] = {}
        self._reports: dict[str, BuildReportSession] = {}
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("CREATE TABLE IF NOT EXISTS web_schema_migrations (version INTEGER PRIMARY KEY)")
            if any(row[0] != 1 for row in db.execute("SELECT version FROM web_schema_migrations")):
                raise RuntimeError("Unsupported web jobs database schema")
            db.execute("CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, state TEXT NOT NULL, "
                       "progress REAL NOT NULL DEFAULT 0, stage TEXT, message TEXT, "
                       "package TEXT, audio TEXT, bundle TEXT, youtube TEXT, reels TEXT)")
            columns = {row["name"] for row in db.execute("PRAGMA table_info(jobs)")}
            for name in ("user_id", "created_at", "started_at", "finished_at", "package_name"):
                if name not in columns:
                    kind = "TEXT" if name in {"user_id", "package_name"} else "REAL"
                    db.execute(f"ALTER TABLE jobs ADD COLUMN {name} {kind}")
            db.execute("CREATE INDEX IF NOT EXISTS jobs_user_id ON jobs(user_id)")
            db.execute("INSERT OR IGNORE INTO web_schema_migrations(version) VALUES(1)")
            db.execute("CREATE UNIQUE INDEX IF NOT EXISTS one_active_web_job ON jobs "
                       "((1)) WHERE state IN ('queued','running','cancelling')")
            # A new server must not claim another live process's render has stopped.
            # Mark orphaned jobs failed at startup below.
            db.execute("CREATE TABLE IF NOT EXISTS owners (job_id TEXT PRIMARY KEY, pid INTEGER)")
            for row in db.execute("SELECT id FROM jobs WHERE state IN ('queued','running','cancelling')"):
                owner = db.execute("SELECT pid FROM owners WHERE job_id=?", (row["id"],)).fetchone()
                alive = False
                if owner:
                    alive = _process_alive(owner["pid"])
                if not alive:
                    db.execute("UPDATE jobs SET state='failed', message='Server stopped during generation' "
                               "WHERE id=?", (row["id"],))
        if retention_days is not None:
            self.purge_uploads(retention_days)

    def purge_uploads(self, days: float) -> list[str]:
        """Delete uploaded inputs of finished jobs older than ``days``; exports are never touched.

        Only directories named after a known finished job inside this storage root qualify.
        """
        cutoff = time.time() - days * 86400
        removed = []
        with self._connect() as db:
            finished = {row["id"] for row in db.execute(
                "SELECT id FROM jobs WHERE state IN ('completed','failed','canceled')")}
        for path in self.root.iterdir():
            if path.is_dir() and path.name in finished and path.stat().st_mtime < cutoff:
                shutil.rmtree(path, ignore_errors=True)
                removed.append(path.name)
        return removed

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.db, timeout=30)
        db.row_factory = sqlite3.Row
        return db

    def create(self, user_id: str | None = None, *, package_name: str | None = None) -> str | None:
        job_id = uuid.uuid4().hex
        try:
            with self._connect() as db:
                db.execute("BEGIN IMMEDIATE")
                if user_id and db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='users'").fetchone():
                    if not db.execute("SELECT 1 FROM users WHERE id=? AND is_active=1 AND must_change_password=0 AND deleted_at IS NULL", (user_id,)).fetchone():
                        raise PermissionError("Account is no longer active")
                db.execute("INSERT INTO jobs(id,state,message,user_id,created_at,package_name) VALUES(?, 'queued', 'Queued', ?, ?, ?)", (job_id, user_id, time.time(), package_name))
                db.execute("INSERT INTO owners(job_id,pid) VALUES(?,?)", (job_id, os.getpid()))
        except sqlite3.IntegrityError:
            return None
        (self.root / job_id).mkdir()
        return job_id

    def update(self, job_id: str, **changes: object) -> None:
        if changes.get("state") == "running":
            changes["started_at"] = time.time()
        if changes.get("state") in {"completed", "failed", "canceled"}:
            changes["finished_at"] = time.time()
        with self._connect() as db:
            fields = ", ".join(f"{key}=?" for key in changes)
            db.execute(f"UPDATE jobs SET {fields} WHERE id=?", (*changes.values(), job_id))

    def get(self, job_id: str) -> dict | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        return dict(row) if row else None

    def active(self) -> dict | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM jobs WHERE state IN ('queued','running','cancelling') LIMIT 1"
            ).fetchone()
        return dict(row) if row else None

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            event = self._cancel.get(job_id)
            if event is None:
                return False
            event.set()
            self.update(job_id, state="cancelling", message="Stopping engine and cleaning up")
            return True

    def options_for(self, job_id: str) -> dict:
        """The switches a job was started with (kept beside it, so a retry keeps them)."""
        try:
            return generation_options(json.loads((self.root / job_id / OPTIONS_FILE).read_text(encoding="utf-8")))
        except (OSError, ValueError):
            return {}

    def start(self, job_id: str, package: Path, audio: Path, options: dict | None = None) -> None:
        chosen = generation_options(options)
        if chosen:
            (self.root / job_id).mkdir(parents=True, exist_ok=True)
            (self.root / job_id / OPTIONS_FILE).write_text(json.dumps(chosen), encoding="utf-8")
        event = threading.Event()
        with self._lock:
            self._cancel[job_id] = event
        self.update(job_id, package=str(package), audio=str(audio))
        threading.Thread(target=self._run, args=(job_id, package, audio, event),
                         daemon=False, name=f"hexa-web-{job_id[:8]}").start()

    def _run(self, job_id: str, package: Path, audio: Path, event: threading.Event) -> None:
        options = self.options_for(job_id)
        settings = replace(self.settings, **sound_options(options))
        report = BuildReportSession(job_id=job_id, settings=settings,
                                    package_path=package, audio_path=audio)
        self._reports[job_id] = report
        final: dict[str, object] = {}
        try:
            if event.is_set():
                raise GenerationCancelledError("generation cancelled by user")
            self.update(job_id, state="running", message="Starting engine")

            def progress(stage, value, message):
                report.on_progress(stage, value, message)
                self.update(job_id, progress=value, stage=stage.value, message=message)

            generate = (StoryEnginePipeline(settings).generate_premiere
                        if options.get("output_kind") == "PREMIERE"
                        else StoryEnginePipeline(settings).generate_bundle)
            result = generate(
                package_path=package, audio_path=audio, job_id=job_id,
                progress=progress, cancelled=event.is_set,
            )
            report.complete(result.manifest_path if options.get("output_kind") == "PREMIERE"
                            else result.youtube.path)
            final = dict(state="completed", progress=1,
                         message="Premiere project ready" if options.get("output_kind") == "PREMIERE" else "Bundle ready",
                         bundle=str(result.directory), youtube=str(result.youtube.path),
                         reels=str(result.reels.path))
        except GenerationCancelledError:
            report.cancel()
            final = dict(state="canceled", message="Generation canceled")
        except Exception as exc:
            report.fail(exc)
            final = dict(state="failed", message=str(exc)[:1000])
        finally:
            with self._lock:
                self._cancel.pop(job_id, None)
                self.update(job_id, **final)
            try:
                self.save_report(job_id, report)
            except Exception:
                # A diagnostic export must not replace the generation result.
                pass

    def save_report(self, job_id: str, report: BuildReportSession) -> Path:
        with self._report_lock:
            directory = self.root / job_id
            temporary = directory / f"diagnostics-{uuid.uuid4().hex}.zip"
            destination = directory / "diagnostics.zip"
            try:
                report.export_zip(temporary)
                temporary.replace(destination)
            finally:
                temporary.unlink(missing_ok=True)
            return destination

    def events(self, job_id: str) -> list[dict]:
        path = self.settings.work_root / job_id / "generation.log"
        if not path.is_file():
            return []
        return [{"line": line} for line in path.read_text(encoding="utf-8", errors="replace").splitlines()[-200:]]

    def report(self, job_id: str) -> BuildReportSession | None:
        return self._reports.get(job_id)
