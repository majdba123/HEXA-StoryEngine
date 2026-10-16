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
    for key, suffix in (("YOUTUBE_16_9", "YOUTUBE"), ("REELS_9_16", "REELS")):
        filename = f"{slug}_{suffix}.mp4"
        if not isinstance(outputs.get(key), dict) or outputs[key].get("filename") != filename:
            return None
        path = bundle / filename
        if not path.is_file() or _is_link(path) or path.stat().st_size <= 0:
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
            db.execute("CREATE INDEX IF NOT EXISTS export_inventory_status ON export_inventory(status)")
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
                discovered.append((f"{package.name}:v{match.group(1)}", package.name,
                                   int(match.group(1)), manifest.get("job_id"), manifest.get("generated_at")))
            if discovered:
                with self.connect() as db:
                    db.executemany("INSERT OR IGNORE INTO export_inventory(id,slug,version,job_id,created_at,status) VALUES(?,?,?,?,?,'AVAILABLE')", discovered)
        self._next_reconcile = time.monotonic() + 60

    def inventory(self, search: str = "", page: int = 1, limit: int = 50):
        self.reconcile()
        with self.connect() as db:
            rows = db.execute("SELECT * FROM export_inventory WHERE slug LIKE ? ORDER BY slug,version DESC LIMIT ? OFFSET ?", (f"%{search}%", limit, (page - 1) * limit)).fetchall()
            total = db.execute("SELECT count(*) FROM export_inventory WHERE slug LIKE ?", (f"%{search}%",)).fetchone()[0]
        items = []
        for row in rows:
            item = dict(row)
            if row["status"] == "AVAILABLE" and self.root is not None and self.secure_root():
                directory = self.root / row["slug"] / f"v{row['version']}"
                item["outputs"] = {}
                if not _is_link(directory) and ExportBundleWriter.is_complete(directory):
                    for kind in ("YOUTUBE", "REELS"):
                        path = directory / f"{row['slug']}_{kind}.mp4"
                        item["outputs"][kind.lower()] = path.stat().st_size if path.is_file() and not _is_link(path) else None
                manifest = directory / "export.json"
                item["bytes"] = sum(value or 0 for value in item["outputs"].values()) + (manifest.stat().st_size if manifest.is_file() and not _is_link(manifest) else 0)
            items.append(item)
        return {"items": items, "total": total}

    def overview(self):
        if self._overview_cache is not None and time.monotonic() < self._overview_until:
            return self._overview_cache
        self.reconcile()
        with self.connect() as db:
            users = db.execute("SELECT count(*) total,sum(is_active=1) active FROM users WHERE deleted_at IS NULL").fetchone()
            jobs = {row["state"]: row["n"] for row in db.execute("SELECT state,count(*) n FROM jobs GROUP BY state")}
            packages = db.execute("SELECT count(DISTINCT slug) FROM export_inventory WHERE status='AVAILABLE'").fetchone()[0]
            bundles = db.execute("SELECT count(*) FROM export_inventory WHERE status='AVAILABLE'").fetchone()[0]
        physical = 0
        count = 0
        if self.root is not None and self.secure_root():
            with self.connect() as db:
                for row in db.execute("SELECT slug,version FROM export_inventory WHERE status='AVAILABLE'"):
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
                "jobs_completed": jobs.get("completed", 0), "jobs_failed": jobs.get("failed", 0),
                "jobs_active": sum(jobs.get(s, 0) for s in ("queued", "running", "cancelling")),
                "packages": packages, "bundles": bundles, "output_files": count,
                "export_bytes": physical, "disk_free_bytes": free_export_bytes(self.root)}
        self._overview_cache = result
        self._overview_until = time.monotonic() + 60
        return result

    def invalidate_overview(self):
        self._overview_until = 0.0

    def history(self, search: str = "", state: str = "", page: int = 1,
                from_at: float | None = None, to_at: float | None = None,
                sort: str = "newest"):
        order = "ASC" if sort == "oldest" else "DESC"
        submitted = "COALESCE((SELECT MIN(created) FROM uploads WHERE job_id=j.id),j.created_at)"
        clause = f"(j.id LIKE ? OR j.package LIKE ? OR j.bundle LIKE ?) AND (?='' OR j.state=?) AND (? IS NULL OR {submitted}>=?) AND (? IS NULL OR {submitted}<?)"
        args = (f"%{search}%", f"%{search}%", f"%{search}%", state, state,
                from_at, from_at, to_at, to_at)
        with self.connect() as db:
            rows = db.execute(f"SELECT j.id,j.state,j.progress,j.created_at,(SELECT MIN(created) FROM uploads WHERE job_id=j.id) AS upload_created_at,j.started_at,j.finished_at,j.user_id,CASE WHEN u.deleted_at IS NULL THEN u.email_normalized END AS user_email,j.bundle FROM jobs j LEFT JOIN users u ON u.id=j.user_id WHERE {clause} ORDER BY COALESCE({submitted},0) {order},j.id {order} LIMIT 50 OFFSET ?", (*args, (page - 1) * 50)).fetchall()
            counts = db.execute(f"SELECT count(*) total,sum(j.state='completed') completed,sum(j.state='failed') failed FROM jobs j WHERE {clause}", args).fetchone()
            bundle_ids = [f"{Path(row['bundle']).parent.name}:{Path(row['bundle']).name}" for row in rows if row["bundle"]]
            statuses = {}
            if bundle_ids:
                slots = ",".join("?" for _ in bundle_ids)
                statuses = {row["id"]: row["status"] for row in db.execute(
                    f"SELECT id,status FROM export_inventory WHERE id IN ({slots})", bundle_ids)}
        items = []
        for row in rows:
            item = dict(row)
            item["submitted_at"] = item.pop("upload_created_at") or item["created_at"]
            bundle = Path(row["bundle"]) if row["bundle"] else None
            bundle_id = f"{bundle.parent.name}:{bundle.name}" if bundle else None
            item["package_name"] = bundle.parent.name if bundle else None
            item["version"] = bundle.name if bundle else None
            item["media_status"] = statuses.get(bundle_id, "UNKNOWN") if bundle_id else "UNKNOWN"
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
