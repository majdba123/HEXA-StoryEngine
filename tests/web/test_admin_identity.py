from __future__ import annotations

from dataclasses import replace
import hashlib
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from fastapi.testclient import TestClient

from app.config import Settings
from app.final.bundle import ExportBundleWriter
from app.web.server import create_app
from app.web.jobs import Jobs
from app.web.identity import Identity
from app.web.admin_data import AdminData
from app.web.uploads import Uploads
from app.web.restore_admin import main as restore_admin
from tests.web.test_uploads import archive, manifest


def setup(tmp_path, monkeypatch):
    monkeypatch.setenv("HEXA_ADMIN_EMAIL", "root@example.invalid")
    monkeypatch.setenv("HEXA_ADMIN_BOOTSTRAP_PASSWORD", "LocalOnlyPassword123!")
    settings = replace(Settings.from_env(), work_root=tmp_path / "work",
                       export_root=tmp_path / "exports", export_min_free_bytes=0)
    return settings, tmp_path / "storage"


def login(client, email="root@example.invalid", password="LocalOnlyPassword123!"):
    response = client.post("/api/session", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return {"X-CSRF-Token": response.json()["csrf"]}


def test_login_rbac_csrf_and_persistent_session(tmp_path, monkeypatch):
    settings, storage = setup(tmp_path, monkeypatch)
    with TestClient(create_app(settings, storage)) as admin:
        assert admin.get("/", follow_redirects=False).status_code == 303
        assert set(admin.get("/ready").json()) == {"ready", "active_job"}
        assert admin.get("/api/jobs/active").status_code == 401
        assert admin.post("/api/session", json={"token": "old-shared-token"}).status_code == 422
        assert admin.post("/api/session", json={"email": "root@example.invalid", "password": "wrong"}).status_code == 401
        headers = login(admin)
        assert admin.get("/admin").status_code == 200
        assert admin.post("/api/admin/users", json={"email": "user@example.invalid", "password": "AnotherGoodPassword123!"}).status_code == 403
        created = admin.post("/api/admin/users", headers=headers, json={"email": "user@example.invalid", "password": "AnotherGoodPassword123!"})
        assert created.status_code == 201, created.text
        user_id = created.json()["id"]
        cookie = admin.cookies.get("hexa_session")
    with TestClient(create_app(settings, storage)) as resumed:
        resumed.cookies.set("hexa_session", cookie)
        assert resumed.get("/admin").status_code == 200
        assert resumed.patch(f"/api/admin/users/{user_id}", json={"is_active": False}).status_code == 403
        assert resumed.patch(f"/api/admin/users/{user_id}", headers=headers, json={"is_active": False}).status_code == 200
    with TestClient(create_app(settings, storage)) as user:
        assert user.post("/api/session", json={"email": "user@example.invalid", "password": "AnotherGoodPassword123!"}).status_code == 401


def test_user_cannot_reach_admin_and_own_upload_scope(tmp_path, monkeypatch):
    settings, storage = setup(tmp_path, monkeypatch)
    with TestClient(create_app(settings, storage)) as admin:
        headers = login(admin)
        for email in ("a@example.invalid", "b@example.invalid"):
            assert admin.post("/api/admin/users", headers=headers, json={"email": email, "password": "AnotherGoodPassword123!"}).status_code == 201
    with TestClient(create_app(settings, storage)) as first, TestClient(create_app(settings, storage)) as second:
        first_headers = login(first, "a@example.invalid", "AnotherGoodPassword123!")
        assert first.get("/admin", follow_redirects=False).status_code == 303
        assert first.get("/api/admin/users").status_code == 403
        assert first.get("/api/jobs/active").status_code == 403  # temporary password gate
        changed = first.post("/api/account/password", headers=first_headers, json={"old_password": "AnotherGoodPassword123!", "new_password": "NewStrongPassword123!"})
        assert changed.status_code == 200
        first_headers = login(first, "a@example.invalid", "NewStrongPassword123!")
        assert first.get("/admin").status_code == 403
        second_headers = login(second, "b@example.invalid", "AnotherGoodPassword123!")
        assert second.post("/api/account/password", headers=second_headers, json={"old_password": "AnotherGoodPassword123!", "new_password": "SecondStrongPassword123!"}).status_code == 200
        second_headers = login(second, "b@example.invalid", "SecondStrongPassword123!")
        package, audio = archive(), b"audio"
        created = first.post("/api/uploads", headers=first_headers,
                             json={"key": "ownership-scope-001", "manifest": manifest(package, audio)})
        assert created.status_code == 201, created.text
        upload_id = created.json()["id"]
        assert first.get(f"/api/uploads/{upload_id}").status_code == 200
        assert second.get(f"/api/uploads/{upload_id}").status_code == 404
        assert second.delete(f"/api/uploads/{upload_id}", headers=second_headers).status_code == 404
        user_id = first.get("/api/session").json()["user"]["id"]
        job_id = Jobs(storage, settings).create(user_id)
        assert first.get(f"/api/jobs/{job_id}").status_code == 200
        assert second.get(f"/api/jobs/{job_id}").status_code == 404
        assert second.get(f"/api/jobs/{job_id}/download/youtube").status_code == 404
        assert second.post(f"/api/jobs/{job_id}/cancel", headers=second_headers).status_code == 404
        with TestClient(create_app(settings, storage)) as administrator:
            admin_headers = login(administrator)
            assert administrator.patch(f"/api/admin/users/{user_id}", headers=admin_headers,
                                       json={"is_active": False}).status_code == 200
        assert first.get("/api/jobs/active").status_code == 401


def test_export_deletion_keeps_history_and_version_number(tmp_path, monkeypatch):
    settings, storage = setup(tmp_path, monkeypatch)
    root = settings.export_root
    root.mkdir()
    writer = ExportBundleWriter(root)
    first = writer.reserve("TEST_PACKAGE")
    for suffix in ("YOUTUBE", "REELS"):
        first.output_path(suffix).write_bytes(b"encoded")
    writer.publish(first, {"completed": True, "export_identity": "TEST_PACKAGE", "export_version": 1,
                           "generated_at": "2026-10-16T00:00:00+00:00", "outputs": {
                               "YOUTUBE_16_9": {"filename": first.output_path("YOUTUBE").name},
                               "REELS_9_16": {"filename": first.output_path("REELS").name}}})
    second = writer.reserve("TEST_PACKAGE")
    for suffix in ("YOUTUBE", "REELS"):
        second.output_path(suffix).write_bytes(b"neighbor")
    writer.publish(second, {"completed": True, "export_identity": "TEST_PACKAGE", "export_version": 2,
                            "generated_at": "2026-10-16T00:01:00+00:00", "outputs": {
                                "YOUTUBE_16_9": {"filename": second.output_path("YOUTUBE").name},
                                "REELS_9_16": {"filename": second.output_path("REELS").name}}})
    malformed = root / "MALICIOUS" / "v1"
    malformed.mkdir(parents=True)
    (malformed / "export.json").write_text(json.dumps({"completed": True, "export_identity": "MALICIOUS",
                                                    "export_version": 1, "outputs": {"YOUTUBE_16_9": {"filename": "../outside.mp4"}}}))
    with TestClient(create_app(settings, storage)) as admin:
        headers = login(admin)
        inventory = admin.get("/api/admin/exports").json()
        assert inventory["total"] == 2
        bundle_id = next(row["id"] for row in inventory["items"] if row["version"] == 1)
        assert next(row for row in inventory["items"] if row["id"] == bundle_id)["created_at"] == "2026-10-16T00:00:00+00:00"
        admin_id = admin.get("/api/session").json()["user"]["id"]
        archived_job = Jobs(storage, settings).create(admin_id)
        assert archived_job is not None
        Jobs(storage, settings).update(
            archived_job, state="completed", bundle=str(first.directory),
            youtube=str(first.output_path("YOUTUBE")), reels=str(first.output_path("REELS")),
        )
        assert admin.get(f"/api/jobs/{archived_job}/download/manifest").status_code == 200
        data = AdminData(storage / "jobs.sqlite3", root)
        assert data.lease_download(bundle_id)
        with pytest.raises(ValueError, match="download"):
            data.delete_bundle(bundle_id, admin_id)
        data.release_download(bundle_id)
        active = Jobs(storage, settings).create(admin_id)
        assert admin.delete(f"/api/admin/exports/{bundle_id}", headers=headers).status_code == 409
        Jobs(storage, settings).update(active, state="failed")
        assert admin.delete(f"/api/admin/exports/{bundle_id}").status_code == 403
        assert admin.delete(f"/api/admin/exports/{bundle_id}", headers=headers).status_code == 200
        assert admin.get(f"/api/jobs/{archived_job}/download/manifest").status_code == 404
        assert admin.get(f"/api/jobs/{archived_job}/download/youtube").status_code == 404
        assert not first.directory.exists()
        assert second.output_path("YOUTUBE").read_bytes() == b"neighbor"
        assert admin.delete(f"/api/admin/exports/{bundle_id}", headers=headers).json()["status"] == "DELETED"
        assert next(row for row in admin.get("/api/admin/exports").json()["items"] if row["id"] == bundle_id)["status"] == "DELETED"
    assert writer.reserve("TEST_PACKAGE").version == 3


def test_last_admin_logout_and_session_expiration(tmp_path, monkeypatch):
    settings, storage = setup(tmp_path, monkeypatch)
    with TestClient(create_app(settings, storage)) as client:
        headers = login(client)
        admin_id = client.get("/api/session").json()["user"]["id"]
        assert client.patch(f"/api/admin/users/{admin_id}", headers=headers,
                            json={"is_active": False}).status_code == 422
        assert client.patch(f"/api/admin/users/{admin_id}", headers=headers,
                            json={"role": "USER"}).status_code == 422
        assert client.get("/api/admin/overview").status_code == 200
        assert client.post("/api/logout", headers=headers).status_code == 200
        assert client.get("/api/admin/overview").status_code == 401
        headers = login(client)
        digest = hashlib.sha256(client.cookies["hexa_session"].encode()).hexdigest()
        with sqlite3.connect(storage / "jobs.sqlite3") as db:
            db.execute("UPDATE identity_sessions SET expires_at=0 WHERE digest=?", (digest,))
        assert client.get("/api/admin/overview").status_code == 401
        assert client.post("/api/logout", headers=headers).status_code == 401


def test_interrupted_export_deletion_is_recovered(tmp_path, monkeypatch):
    settings, storage = setup(tmp_path, monkeypatch)
    root = settings.export_root
    root.mkdir()
    writer = ExportBundleWriter(root)
    bundle = writer.reserve("RECOVERY")
    for suffix in ("YOUTUBE", "REELS"):
        bundle.output_path(suffix).write_bytes(b"encoded")
    writer.publish(bundle, {"completed": True, "export_identity": "RECOVERY", "export_version": 1,
                            "outputs": {"YOUTUBE_16_9": {"filename": bundle.output_path("YOUTUBE").name},
                                        "REELS_9_16": {"filename": bundle.output_path("REELS").name}}})
    with TestClient(create_app(settings, storage)) as client:
        login(client)
        assert client.get("/api/admin/exports").json()["total"] == 1
    tombstone = bundle.directory.with_name("v1.deleted")
    deleting = bundle.directory.with_name("v1.deleting")
    tombstone.mkdir()
    bundle.directory.rename(deleting)
    with sqlite3.connect(storage / "jobs.sqlite3") as db:
        db.execute("UPDATE export_inventory SET status='DELETING' WHERE id='RECOVERY:v1'")
    with TestClient(create_app(settings, storage)) as client:
        login(client)
        row = client.get("/api/admin/exports").json()["items"][0]
        assert row["status"] == "DELETED"
    assert not deleting.exists() and tombstone.is_dir()
    assert writer.reserve("RECOVERY").version == 2


def test_bootstrap_does_not_recreate_disabled_admin_and_offline_recovery(tmp_path, monkeypatch):
    settings, storage = setup(tmp_path, monkeypatch)
    with TestClient(create_app(settings, storage)) as client:
        login(client)
    database = storage / "jobs.sqlite3"
    with sqlite3.connect(database) as db:
        db.execute("UPDATE users SET is_active=0 WHERE role='ADMIN'")
    with pytest.raises(RuntimeError, match="No active administrator"):
        with TestClient(create_app(settings, storage)):
            pass
    answers = iter(("RecoveryPassword123!", "RecoveryPassword123!"))
    monkeypatch.setattr("getpass.getpass", lambda _: next(answers))
    monkeypatch.setattr("sys.argv", ["restore_admin", "--db", str(database),
                                   "--email", "recovery@example.invalid", "--backup-confirmed"])
    restore_admin()
    with TestClient(create_app(settings, storage)) as client:
        assert client.post("/api/session", json={"email": "root@example.invalid",
                                                  "password": "LocalOnlyPassword123!"}).status_code == 401
        assert client.post("/api/session", json={"email": "recovery@example.invalid",
                                                  "password": "RecoveryPassword123!"}).status_code == 200


def test_https_session_cookie_is_secure_and_http_only(tmp_path, monkeypatch):
    settings, storage = setup(tmp_path, monkeypatch)
    with TestClient(create_app(settings, storage), base_url="https://testserver") as client:
        response = client.post("/api/session", json={"email": "root@example.invalid",
                                                     "password": "LocalOnlyPassword123!"})
        assert response.status_code == 200
        cookies = response.headers.get_list("set-cookie")
        session_cookie = next(value.lower() for value in cookies if value.startswith("hexa_session="))
        assert "secure" in session_cookie and "httponly" in session_cookie and "samesite=strict" in session_cookie
        assert client.get("/api/admin/overview").status_code == 200


def test_login_rate_limit_uses_persisted_attempts(tmp_path, monkeypatch):
    settings, storage = setup(tmp_path, monkeypatch)
    with TestClient(create_app(settings, storage)) as client:
        for _ in range(8):
            assert client.post("/api/session", json={"email": "root@example.invalid",
                                                      "password": "WrongPassword123!"}).status_code == 401
        assert client.post("/api/session", json={"email": "root@example.invalid",
                                                  "password": "LocalOnlyPassword123!"}).status_code == 401
    with TestClient(create_app(settings, storage)) as restarted:
        assert restarted.post("/api/session", json={"email": "root@example.invalid",
                                                    "password": "LocalOnlyPassword123!"}).status_code == 401
    with sqlite3.connect(storage / "jobs.sqlite3") as db:
        db.execute("UPDATE login_attempts SET until=0")
    with TestClient(create_app(settings, storage)) as client:
        assert client.post("/api/session", json={"email": "root@example.invalid",
                                                  "password": "LocalOnlyPassword123!"}).status_code == 200


def test_legacy_job_schema_is_migrated_without_assigning_owner(tmp_path, monkeypatch):
    settings, storage = setup(tmp_path, monkeypatch)
    storage.mkdir()
    with sqlite3.connect(storage / "jobs.sqlite3") as db:
        db.execute("CREATE TABLE jobs (id TEXT PRIMARY KEY, state TEXT NOT NULL, progress REAL NOT NULL DEFAULT 0, stage TEXT, message TEXT, package TEXT, audio TEXT, bundle TEXT, youtube TEXT, reels TEXT)")
        db.execute("INSERT INTO jobs(id,state,message) VALUES('old-job','completed','legacy')")
    with TestClient(create_app(settings, storage)) as admin:
        headers = login(admin)
        assert admin.get("/api/jobs/old-job").status_code == 200
        assert admin.get("/api/admin/history").json()["items"][0]["submitted_at"] is None
        created = admin.post("/api/admin/users", headers=headers,
                             json={"email": "ordinary@example.invalid", "password": "AnotherGoodPassword123!"})
        assert created.status_code == 201
    with TestClient(create_app(settings, storage)) as ordinary:
        headers = login(ordinary, "ordinary@example.invalid", "AnotherGoodPassword123!")
        assert ordinary.post("/api/account/password", headers=headers,
                             json={"old_password": "AnotherGoodPassword123!",
                                   "new_password": "NewStrongPassword123!"}).status_code == 200
        login(ordinary, "ordinary@example.invalid", "NewStrongPassword123!")
        assert ordinary.get("/api/jobs/old-job").status_code == 404
    with sqlite3.connect(storage / "jobs.sqlite3") as db:
        assert db.execute("SELECT user_id,created_at FROM jobs WHERE id='old-job'").fetchone() == (None, None)


def test_legacy_upload_is_visible_only_to_admin(tmp_path, monkeypatch):
    settings, storage = setup(tmp_path, monkeypatch)
    jobs = Jobs(storage, settings)
    uploads = Uploads(storage, jobs, 10_000_000, storage / "uploads")
    package, audio = archive(), b"audio"
    legacy = uploads.initialize("old-shared-owner-hash", "old-upload-key-0001", manifest(package, audio))
    with TestClient(create_app(settings, storage)) as admin:
        headers = login(admin)
        assert admin.get(f"/api/uploads/{legacy['id']}").status_code == 200
        assert admin.post("/api/admin/users", headers=headers,
                          json={"email": "ordinary@example.invalid", "password": "AnotherGoodPassword123!"}).status_code == 201
    with TestClient(create_app(settings, storage)) as ordinary:
        headers = login(ordinary, "ordinary@example.invalid", "AnotherGoodPassword123!")
        assert ordinary.post("/api/account/password", headers=headers,
                             json={"old_password": "AnotherGoodPassword123!",
                                   "new_password": "NewStrongPassword123!"}).status_code == 200
        login(ordinary, "ordinary@example.invalid", "NewStrongPassword123!")
        assert ordinary.get(f"/api/uploads/{legacy['id']}").status_code == 404


def test_clean_database_without_bootstrap_secrets_fails_closed(tmp_path, monkeypatch):
    settings, storage = setup(tmp_path, monkeypatch)
    monkeypatch.delenv("HEXA_ADMIN_EMAIL")
    monkeypatch.delenv("HEXA_ADMIN_BOOTSTRAP_PASSWORD")
    with pytest.raises(RuntimeError, match="Initial administrator requires"):
        with TestClient(create_app(settings, storage)):
            pass


def test_concurrent_admin_changes_keep_one_active_admin(tmp_path, monkeypatch):
    settings, storage = setup(tmp_path, monkeypatch)
    with TestClient(create_app(settings, storage)) as client:
        login(client)
        first_id = client.get("/api/session").json()["user"]["id"]
    identity = Identity(storage / "jobs.sqlite3")
    second_id = identity.create_user(first_id, "second-admin@example.invalid",
                                     "AnotherGoodPassword123!", "ADMIN")["id"]
    with identity.connect() as db:
        db.execute("UPDATE users SET must_change_password=0 WHERE id=?", (second_id,))
    def demote(actor, target):
        try:
            identity.change_user(actor, target, {"role": "USER"})
            return True
        except (PermissionError, ValueError):
            return False
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda pair: demote(*pair),
                                 ((first_id, second_id), (second_id, first_id))))
    assert outcomes.count(True) == 1
    with identity.connect() as db:
        assert db.execute("SELECT count(*) FROM users WHERE role='ADMIN' AND is_active=1 AND deleted_at IS NULL").fetchone()[0] == 1


def test_failed_render_history_keeps_validated_package_name(tmp_path, monkeypatch):
    settings, storage = setup(tmp_path, monkeypatch)
    with TestClient(create_app(settings, storage)) as client:
        login(client)
        admin_id = client.get("/api/session").json()["user"]["id"]
        failed_id = Jobs(storage, settings).create(admin_id, package_name="BLACK_HAT_HACKER")
        assert failed_id is not None
        Jobs(storage, settings).update(failed_id, state="failed", message="Encoder failed")
        result = client.get("/api/admin/history?search=BLACK_HAT_HACKER")
        assert result.status_code == 200, result.text
        rows = result.json()["items"]
        assert len(rows) == 1
        assert rows[0]["id"] == failed_id
        assert rows[0]["state"] == "failed"
        assert rows[0]["package_name"] == "BLACK_HAT_HACKER"
        assert rows[0]["version"] is None
