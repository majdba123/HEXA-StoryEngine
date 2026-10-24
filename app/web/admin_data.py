"""Read-only admin counts and bounded export inventory."""
from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import time
import threading
from contextlib import contextmanager
from pathlib import Path

from app.final.bundle import ExportBundleWriter, export_slug, _is_link
from app.shared.errors import StageFailedError

VERSION = re.compile(r"^v([1-9][0-9]{0,5})$")
SLUG = re.compile(r"^[A-Z0-9_-]{1,80}$")


def safe_slug(value: str) -> bool:
    if not SLUG.fullmatch(value):
        return False
    try:
        return export_slug(value) == value
    except StageFailedError:
        return False


def valid_manifest(bundle: Path, slug: str, version: int) -> dict | None:
    if _is_link(bundle) or _is_link(bundle / "export.json") or not ExportBundleWriter.is_complete(bundle):
        return None
    try:
        manifest = json.loads((bundle / "export.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(manifest, dict) or manifest.get("export_identity") != slug or manifest.get("export_version") != version:
        return None
    outputs = manifest.get("outputs")
    if not isinstance(outputs, dict):
        return None
    premiere = manifest.get("schema") == "hexa.export.premiere/1"
    if not premiere and manifest.get("schema") not in (None, "hexa.export.bundle/1"):
        return None
    for key, suffix in (("YOUTUBE_16_9", "YOUTUBE"), ("REELS_9_16", "REELS")):
        row = outputs.get(key)
        filename = f"{slug}_{suffix}_PREMIERE.xml" if premiere else f"{slug}_{suffix}.mp4"
        if not isinstance(row, dict) or row.get("filename") != filename:
            return None
        path = bundle / filename
        if not path.is_file() or _is_link(path) or path.stat().st_size <= 0:
            return None
        if premiere:
            media_name = f"{slug}_{suffix}_PREMIERE_media"
            media = bundle / media_name
            if row.get("kind") != "premiere_fcp7_xml" or row.get("media_dir") != media_name or not media.is_dir() or _is_link(media):
                return None
    return manifest


def free_export_bytes(root: Path | None) -> int | None:
    if root is None:
        return None
    candidate = root
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    try:
        return shutil.disk_usage(candidate).free if candidate.exists() else None
    except OSError:
        return None


class AdminData:
    def __init__(self, database: Path, export_root: Path | None):
        self.database = database
        self.configured_root = export_root
        self.valid_root = bool(export_root and export_root.is_absolute())
        self.root = export_root.resolve() if export_root else None
        self._next_reconcile = 0.0
        self._overview_cache = None
        self._overview_until = 0.0
        self._delete_lock = threading.RLock()
        self._reconcile_lock = threading.Lock()
        self._downloads: dict[str, int] = {}
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("CREATE TABLE IF NOT EXISTS admin_schema (version INTEGER PRIMARY KEY)")
            if any(row[0] != 1 for row in db.execute("SELECT version FROM admin_schema")):
                raise RuntimeError("Unsupported administration database schema")
            db.execute("CREATE TABLE IF NOT EXISTS export_inventory (id TEXT PRIMARY KEY, slug TEXT NOT NULL, version INTEGER NOT NULL, job_id TEXT, created_at TEXT, status TEXT NOT NULL, deleted_at REAL, deleted_by TEXT, UNIQUE(slug,version))")
            if "kind" not in {row["name"] for row in db.execute("PRAGMA table_info(export_inventory)")}:
                db.execute("ALTER TABLE export_inventory ADD COLUMN kind TEXT NOT NULL DEFAULT 'VIDEO'")
            db.execute("CREATE INDEX IF NOT EXISTS export_inventory_status ON export_inventory(status)")
            db.execute("CREATE INDEX IF NOT EXISTS export_inventory_job ON export_inventory(job_id)")
            db.execute("INSERT OR IGNORE INTO admin_schema(version) VALUES(1)")

    def secure_root(self) -> bool:
        return bool(self.valid_root and self.configured_root and self.root and
                    self.configured_root.resolve() == self.root and
                    not any(_is_link(path) for path in (self.configured_root, *self.configured_root.parents)))

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.database, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def reconcile(self):
        if not self._reconcile_lock.acquire(blocking=False):
            return
        try:
            self._reconcile_once()
        finally:
            self._reconcile_lock.release()

    def _reconcile_once(self):
        if time.monotonic() < self._next_reconcile:
            return
        if not self.secure_root() or self.root is None or not self.root.is_dir():
            return
        with self.connect() as db:
            if db.execute("SELECT 1 FROM jobs WHERE state IN ('queued','running','cancelling') LIMIT 1").fetchone():
                return
            completed_jobs = {row["bundle"]: row["id"] for row in db.execute(
                "SELECT id,bundle FROM jobs WHERE state='completed' AND bundle IS NOT NULL")}
        for package in self.root.iterdir():
            if not package.is_dir() or _is_link(package) or not safe_slug(package.name):
                continue
            discovered = []
            for bundle in package.iterdir():
                match = VERSION.fullmatch(bundle.name)
                if not match or not bundle.is_dir():
                    continue
                manifest = valid_manifest(bundle, package.name, int(match.group(1)))
                if manifest is None:
                    continue
                job_id = completed_jobs.get(str(bundle))
                discovered.append((f"{package.name}:v{match.group(1)}", package.name,
                                   int(match.group(1)), job_id, manifest.get("generated_at"),
                                   "PREMIERE" if manifest.get("schema") == "hexa.export.premiere/1" else "VIDEO"))
            if discovered:
                with self.connect() as db:
                    db.executemany("INSERT OR IGNORE INTO export_inventory(id,slug,version,job_id,created_at,kind,status) VALUES(?,?,?,?,?,?,'AVAILABLE')", discovered)
                    db.executemany("UPDATE export_inventory SET job_id=? WHERE id=? AND job_id IS NULL AND status='AVAILABLE'", ((row[3], row[0]) for row in discovered if row[3]))
        self._next_reconcile = time.monotonic() + 60

    def inventory(self, search: str = "", page: int = 1, limit: int = 50, kind: str = "VIDEO"):
        self.reconcile()
        with self.connect() as db:
            rows = db.execute("SELECT e.*,u.email_normalized AS user_email FROM export_inventory e LEFT JOIN jobs j ON j.id=e.job_id LEFT JOIN users u ON u.id=j.user_id WHERE e.kind=? AND e.slug LIKE ? ORDER BY e.slug,e.version DESC LIMIT ? OFFSET ?", (kind, f"%{search}%", limit, (page - 1) * limit)).fetchall()
            total = db.execute("SELECT count(*) FROM export_inventory WHERE kind=? AND slug LIKE ?", (kind, f"%{search}%")).fetchone()[0]
        items = []
        for row in rows:
            item = dict(row)
            if row["status"] == "AVAILABLE" and self.root is not None and self.secure_root():
                directory = self.root / row["slug"] / f"v{row['version']}"
                item["outputs"] = {}
                if not _is_link(directory) and ExportBundleWriter.is_complete(directory):
                    for suffix in ("YOUTUBE", "REELS"):
                        filename = f"{row['slug']}_{suffix}_PREMIERE.xml" if row["kind"] == "PREMIERE" else f"{row['slug']}_{suffix}.mp4"
                        path = directory / filename
                        item["outputs"][suffix.lower()] = path.stat().st_size if path.is_file() and not _is_link(path) else None
                manifest = directory / "export.json"
                item["bytes"] = sum(value or 0 for value in item["outputs"].values()) + (manifest.stat().st_size if manifest.is_file() and not _is_link(manifest) else 0)
            items.append(item)
        return {"items": items, "total": total}

    def premiere_files(self, bundle_id: str) -> tuple[Path, list[Path]]:
        """Return only verified project files below a complete Premiere bundle."""
        if not self.secure_root() or self.root is None:
            raise LookupError("Export root is not configured")
        with self.connect() as db:
            row = db.execute("SELECT slug,version FROM export_inventory WHERE id=? AND kind='PREMIERE' AND status='AVAILABLE'", (bundle_id,)).fetchone()
        if row is None or not safe_slug(row["slug"]):
            raise LookupError("Premiere project unavailable")
        directory = self.root / row["slug"] / f"v{row['version']}"
        if _is_link(directory.parent) or _is_link(directory) or directory.resolve() != self.root / row["slug"] / f"v{row['version']}":
            raise LookupError("Premiere project unavailable")
        manifest = valid_manifest(directory, row["slug"], row["version"])
        if manifest is None or manifest.get("schema") != "hexa.export.premiere/1":
            raise LookupError("Premiere project unavailable")
        files = [directory / "export.json"]
        for key in ("YOUTUBE_16_9", "REELS_9_16"):
            output = manifest["outputs"][key]
            files.append(directory / output["filename"])
            media = directory / output["media_dir"]
            for base, dirs, names in os.walk(media, followlinks=False):
                for name in dirs + names:
                    path = Path(base) / name
                    if _is_link(path) or not path.resolve().is_relative_to(directory):
                        raise LookupError("Premiere project contains an unsafe path")
                    if path.is_file():
                        files.append(path)
        if any(not path.is_file() or _is_link(path) for path in files):
            raise LookupError("Premiere project unavailable")
        return directory, files

    def overview(self, force: bool = False):
        if force:
            self._overview_until = 0.0
            self._next_reconcile = 0.0
        if self._overview_cache is not None and time.monotonic() < self._overview_until:
            return self._overview_cache
        self.reconcile()
        with self.connect() as db:
            users = db.execute("SELECT count(*) total,sum(is_active=1) active FROM users WHERE deleted_at IS NULL").fetchone()
            users_all = db.execute("SELECT count(*) FROM users").fetchone()[0]
            jobs = {row["state"]: row["n"] for row in db.execute("SELECT state,count(*) n FROM jobs GROUP BY state")}
            historic = db.execute("SELECT count(*) total, sum(kind='VIDEO') videos, sum(kind='PREMIERE') premiere, sum(status='DELETED') deleted FROM export_inventory").fetchone()
            packages = db.execute("SELECT count(DISTINCT slug) FROM export_inventory WHERE status='AVAILABLE'").fetchone()[0]
            bundles = db.execute("SELECT count(*) FROM export_inventory WHERE kind='VIDEO' AND status='AVAILABLE'").fetchone()[0]
            premiere_projects = db.execute("SELECT count(*) FROM export_inventory WHERE kind='PREMIERE' AND status='AVAILABLE'").fetchone()[0]
        physical = 0
        count = 0
        if self.root is not None and self.secure_root():
            with self.connect() as db:
                for row in db.execute("SELECT slug,version FROM export_inventory WHERE kind='VIDEO' AND status='AVAILABLE'"):
                    directory = self.root / row["slug"] / f"v{row['version']}"
                    if _is_link(directory) or not ExportBundleWriter.is_complete(directory):
                        continue
                    for suffix in ("YOUTUBE", "REELS"):
                        path = directory / f"{row['slug']}_{suffix}.mp4"
                        if path.is_file() and not _is_link(path):
                            physical += path.stat().st_size
                            count += 1
                    manifest = directory / "export.json"
                    if manifest.is_file() and not _is_link(manifest):
                        physical += manifest.stat().st_size
        result = {"users_total": users["total"], "users_active": users["active"] or 0,
                "users_disabled": users["total"] - (users["active"] or 0),
                "users_historical": users_all, "jobs_total": sum(jobs.values()),
                "jobs_completed": jobs.get("completed", 0), "jobs_failed": jobs.get("failed", 0),
                "jobs_canceled": jobs.get("canceled", 0),
                "jobs_active": sum(jobs.get(s, 0) for s in ("queued", "running", "cancelling")),
                "exports_historical": historic["total"], "videos_historical": historic["videos"] or 0,
                "premiere_historical": historic["premiere"] or 0,
                "exports_deleted": historic["deleted"] or 0,
                "packages": packages, "bundles": bundles, "premiere_projects": premiere_projects,
                "output_files": count,
                "export_bytes": physical, "disk_free_bytes": free_export_bytes(self.root)}
        self._overview_cache = result
        self._overview_until = time.monotonic() + 60
        return result

    def user_stats(self, user_ids: list[str]) -> dict[str, dict]:
        """Durable per-owner counts: deleted media and disabled users retain their rows."""
        if not user_ids:
            return {}
        self.reconcile()
        slots = ",".join("?" for _ in user_ids)
        stats = {user_id: {"jobs_total": 0, "completed": 0, "failed": 0,
                           "canceled": 0, "active": 0, "videos": 0,
                           "premiere": 0, "deleted_exports": 0, "available_exports": 0,
                           "last_job_at": None} for user_id in user_ids}
        with self.connect() as db:
            for row in db.execute(
                f"SELECT user_id,count(*) jobs_total,sum(state='completed') completed,"
                f"sum(state='failed') failed,sum(state='canceled') canceled,"
                f"sum(state IN ('queued','running','cancelling')) active,"
                f"max(created_at) last_job_at FROM jobs WHERE user_id IN ({slots}) GROUP BY user_id",
                user_ids,
            ):
                stats[row["user_id"]].update({key: row[key] or 0 for key in
                                               ("jobs_total", "completed", "failed", "canceled", "active")})
                stats[row["user_id"]]["last_job_at"] = row["last_job_at"]
            for row in db.execute(
                f"SELECT j.user_id,sum(e.kind='VIDEO') videos,sum(e.kind='PREMIERE') premiere,"
                f"sum(e.status='DELETED') deleted_exports,sum(e.status='AVAILABLE') available_exports "
                f"FROM export_inventory e JOIN jobs j ON j.id=e.job_id "
                f"WHERE j.user_id IN ({slots}) GROUP BY j.user_id", user_ids,
            ):
                stats[row["user_id"]].update({key: row[key] or 0 for key in
                                               ("videos", "premiere", "deleted_exports", "available_exports")})
        return stats

    def invalidate_overview(self):
        self._overview_until = 0.0

    def history(self, search: str = "", state: str = "", page: int = 1,
                from_at: float | None = None, to_at: float | None = None,
                sort: str = "newest", user_id: str | None = None):
        self.reconcile()
        order = "ASC" if sort == "oldest" else "DESC"
        submitted = "COALESCE((SELECT MIN(created) FROM uploads WHERE job_id=j.id),j.created_at)"
        clause = f"(j.id LIKE ? OR j.package_name LIKE ? OR j.package LIKE ? OR j.bundle LIKE ? OR j.user_id IN (SELECT id FROM users WHERE email_normalized LIKE ?)) AND (?='' OR j.state=?) AND (? IS NULL OR {submitted}>=?) AND (? IS NULL OR {submitted}<?) AND (? IS NULL OR j.user_id=?)"
        args = (f"%{search}%", f"%{search}%", f"%{search}%", f"%{search}%", f"%{search}%", state, state,
                from_at, from_at, to_at, to_at, user_id, user_id)
        with self.connect() as db:
            rows = db.execute(f"SELECT j.id,j.state,j.progress,j.created_at,j.package_name,(SELECT MIN(created) FROM uploads WHERE job_id=j.id) AS upload_created_at,j.started_at,j.finished_at,j.user_id,u.email_normalized AS user_email,j.bundle FROM jobs j LEFT JOIN users u ON u.id=j.user_id WHERE {clause} ORDER BY COALESCE({submitted},0) {order},j.id {order} LIMIT 50 OFFSET ?", (*args, (page - 1) * 50)).fetchall()
            counts = db.execute(f"SELECT count(*) total,sum(j.state='completed') completed,sum(j.state='failed') failed FROM jobs j WHERE {clause}", args).fetchone()
            bundle_ids = [f"{Path(row['bundle']).parent.name}:{Path(row['bundle']).name}" for row in rows if row["bundle"]]
            statuses = {}
            if bundle_ids:
                slots = ",".join("?" for _ in bundle_ids)
                statuses = {row["id"]: (row["status"], row["kind"]) for row in db.execute(
                    f"SELECT id,status,kind FROM export_inventory WHERE id IN ({slots})", bundle_ids)}
        items = []
        for row in rows:
            item = dict(row)
            item["submitted_at"] = item.pop("upload_created_at") or item["created_at"]
            bundle = Path(row["bundle"]) if row["bundle"] else None
            bundle_id = f"{bundle.parent.name}:{bundle.name}" if bundle else None
            item["package_name"] = bundle.parent.name if bundle else (row["package_name"] or None)
            item["version"] = bundle.name if bundle else None
            item["bundle_id"] = bundle_id
            item["media_status"], item["media_kind"] = statuses.get(bundle_id, ("UNKNOWN", None))
            item.pop("bundle")
            items.append(item)
        return {"items": items, "total": counts["total"], "completed": counts["completed"] or 0,
                "failed": counts["failed"] or 0}

    def lease_download(self, bundle_id: str):
        with self._delete_lock:
            with self.connect() as db:
                row = db.execute("SELECT status FROM export_inventory WHERE id=?", (bundle_id,)).fetchone()
            if row and row["status"] != "AVAILABLE":
                return False
            self._downloads[bundle_id] = self._downloads.get(bundle_id, 0) + 1
            return True

    def release_download(self, bundle_id: str):
        with self._delete_lock:
            self._downloads[bundle_id] = max(0, self._downloads.get(bundle_id, 1) - 1)

    def delete_bundle(self, bundle_id: str, actor: str):
        if not self.secure_root() or self.root is None:
            raise ValueError("Export root is not configured")
        with self._delete_lock:
            with self.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                if not db.execute("SELECT 1 FROM users WHERE id=? AND role='ADMIN' AND is_active=1 AND must_change_password=0 AND deleted_at IS NULL", (actor,)).fetchone():
                    raise PermissionError("Administrator session was revoked")
                row = db.execute("SELECT slug,version,status FROM export_inventory WHERE id=?", (bundle_id,)).fetchone()
                if not row:
                    raise LookupError("Export not found")
                if row["status"] == "DELETED":
                    return {"status": "DELETED", "id": bundle_id}
                if row["status"] != "AVAILABLE":
                    raise ValueError("Export deletion is already in progress")
                if db.execute("SELECT 1 FROM jobs WHERE state IN ('queued','running','cancelling') LIMIT 1").fetchone():
                    raise ValueError("A rendering job is active")
                if self._downloads.get(bundle_id, 0):
                    raise ValueError("An export download is active")
                slug, version = row["slug"], row["version"]
                if not safe_slug(slug) or version < 1:
                    raise ValueError("Unsafe export identity")
                package = self.root / slug
                directory = package / f"v{version}"
                deleting = package / f"v{version}.deleting"
                tombstone = package / f"v{version}.deleted"
                if (not self.secure_root() or _is_link(package) or _is_link(directory) or not directory.is_dir() or
                        package.resolve() != self.root / slug or directory.resolve() != package / f"v{version}" or
                        valid_manifest(directory, slug, version) is None or tombstone.exists() or deleting.exists()):
                    raise ValueError("Export path is unsafe or incomplete")
                for base, dirs, files in os.walk(directory, followlinks=False):
                    if any(_is_link(Path(base) / name) for name in dirs + files):
                        raise ValueError("Export contains a link")
                tombstone.mkdir()
                db.execute("UPDATE export_inventory SET status='DELETING',deleted_by=?,deleted_at=? WHERE id=?", (actor, time.time(), bundle_id))
                db.execute("INSERT INTO identity_audit(actor_id,action,target_id,happened_at) VALUES(?,?,?,?)", (actor, "export_delete_requested", bundle_id, time.time()))
            try:
                directory.rename(deleting)
                shutil.rmtree(deleting)
            except OSError:
                with self.connect() as db:
                    db.execute("UPDATE export_inventory SET status='DELETE_FAILED' WHERE id=?", (bundle_id,))
                    db.execute("INSERT INTO identity_audit(actor_id,action,target_id,happened_at) VALUES(?,?,?,?)", (actor, "export_delete_failed", bundle_id, time.time()))
                raise
            with self.connect() as db:
                db.execute("UPDATE export_inventory SET status='DELETED' WHERE id=?", (bundle_id,))
                db.execute("INSERT INTO identity_audit(actor_id,action,target_id,happened_at) VALUES(?,?,?,?)", (actor, "export_deleted", bundle_id, time.time()))
            self._overview_until = 0
            return {"status": "DELETED", "id": bundle_id}

    def recover_deletions(self):
        """Complete durable deletions interrupted after the DELETING commit."""
        if not self.secure_root() or self.root is None:
            return
        with self._delete_lock:
            with self.connect() as db:
                rows = db.execute("SELECT id,slug,version,deleted_by FROM export_inventory WHERE status='DELETING'").fetchall()
            for row in rows:
                bundle_id, slug, version = row["id"], row["slug"], row["version"]
                package = self.root / slug
                source = package / f"v{version}"
                deleting = package / f"v{version}.deleting"
                tombstone = package / f"v{version}.deleted"
                try:
                    if (not safe_slug(slug) or version < 1 or _is_link(self.configured_root) or
                            _is_link(package) or not tombstone.is_dir() or _is_link(tombstone) or
                            _is_link(source) or _is_link(deleting) or (source.exists() and deleting.exists())):
                        raise ValueError("Unsafe interrupted deletion")
                    if source.exists():
                        source.rename(deleting)
                    if deleting.exists():
                        for base, dirs, files in os.walk(deleting, followlinks=False):
                            if any(_is_link(Path(base) / name) for name in dirs + files):
                                raise ValueError("Interrupted export contains a link")
                        shutil.rmtree(deleting)
                    with self.connect() as db:
                        db.execute("UPDATE export_inventory SET status='DELETED' WHERE id=?", (bundle_id,))
                        db.execute("INSERT INTO identity_audit(actor_id,action,target_id,happened_at) VALUES(?,?,?,?)", (row["deleted_by"], "export_delete_recovered", bundle_id, time.time()))
                except (OSError, ValueError):
                    with self.connect() as db:
                        db.execute("UPDATE export_inventory SET status='DELETE_FAILED' WHERE id=?", (bundle_id,))
                        db.execute("INSERT INTO identity_audit(actor_id,action,target_id,happened_at) VALUES(?,?,?,?)", (row["deleted_by"], "export_delete_resume_failed", bundle_id, time.time()))
