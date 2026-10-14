from __future__ import annotations

import sqlite3
import threading
import uuid
import os
from pathlib import Path

from app.config import Settings
from app.diagnostics import BuildReportSession
from app.pipeline import StoryEnginePipeline
from app.shared.errors import GenerationCancelledError


class Jobs:
    """One worker per server process; SQLite admission also excludes other processes."""

    def __init__(self, root: Path, settings: Settings) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.settings = settings
        self.db = self.root / "jobs.sqlite3"
        self._lock = threading.Lock()
        self._cancel: dict[str, threading.Event] = {}
        self._reports: dict[str, BuildReportSession] = {}
        with self._connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, state TEXT NOT NULL, "
                       "progress REAL NOT NULL DEFAULT 0, stage TEXT, message TEXT, "
                       "package TEXT, audio TEXT, bundle TEXT, youtube TEXT, reels TEXT)")
            db.execute("CREATE UNIQUE INDEX IF NOT EXISTS one_active_web_job ON jobs "
                       "((1)) WHERE state IN ('queued','running','cancelling')")
            # A new server must not claim another live process's render has stopped.
            # Recovery of an orphaned render is handled at startup below.
            db.execute("CREATE TABLE IF NOT EXISTS owners (job_id TEXT PRIMARY KEY, pid INTEGER)")
            for row in db.execute("SELECT id FROM jobs WHERE state IN ('queued','running','cancelling')"):
                owner = db.execute("SELECT pid FROM owners WHERE job_id=?", (row["id"],)).fetchone()
                alive = False
                if owner:
                    try:
                        os.kill(owner["pid"], 0)
                        alive = True
                    except OSError:
                        pass
                if not alive:
                    db.execute("UPDATE jobs SET state='failed', message='Server stopped during generation' "
                               "WHERE id=?", (row["id"],))

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.db, timeout=30)
        db.row_factory = sqlite3.Row
        return db

    def create(self) -> str | None:
        job_id = uuid.uuid4().hex
        try:
            with self._connect() as db:
                db.execute("INSERT INTO jobs(id,state,message) VALUES(?, 'queued', 'Queued')", (job_id,))
                db.execute("INSERT INTO owners(job_id,pid) VALUES(?,?)", (job_id, os.getpid()))
        except sqlite3.IntegrityError:
            return None
        (self.root / job_id).mkdir()
        return job_id

    def update(self, job_id: str, **changes: object) -> None:
        with self._connect() as db:
            fields = ", ".join(f"{key}=?" for key in changes)
            db.execute(f"UPDATE jobs SET {fields} WHERE id=?", (*changes.values(), job_id))

    def get(self, job_id: str) -> dict | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        return dict(row) if row else None

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            event = self._cancel.get(job_id)
            if event is None:
                return False
            event.set()
            self.update(job_id, state="cancelling", message="Stopping engine and cleaning up")
            return True

    def start(self, job_id: str, package: Path, audio: Path) -> None:
        event = threading.Event()
        with self._lock:
            self._cancel[job_id] = event
        self.update(job_id, package=str(package), audio=str(audio))
        threading.Thread(target=self._run, args=(job_id, package, audio, event),
                         daemon=False, name=f"hexa-web-{job_id[:8]}").start()

    def _run(self, job_id: str, package: Path, audio: Path, event: threading.Event) -> None:
        report = BuildReportSession(job_id=job_id, settings=self.settings,
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

            result = StoryEnginePipeline(self.settings).generate_bundle(
                package_path=package, audio_path=audio, job_id=job_id,
                progress=progress, cancelled=event.is_set,
            )
            report.complete(result.youtube.path)
            final = dict(state="completed", progress=1, message="Bundle ready",
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

    def events(self, job_id: str) -> list[dict]:
        path = self.settings.work_root / job_id / "generation.log"
        if not path.is_file():
            return []
        return [{"line": line} for line in path.read_text(encoding="utf-8", errors="replace").splitlines()[-200:]]

    def report(self, job_id: str) -> BuildReportSession | None:
        return self._reports.get(job_id)
