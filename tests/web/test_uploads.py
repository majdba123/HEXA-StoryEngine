from __future__ import annotations
import hashlib
import io
import os
import zipfile
from dataclasses import replace
from tests.web.auth_client import AuthenticatedTestClient as TestClient
from fastapi.testclient import TestClient as RawTestClient
from app.config import Settings
from app.web.server import create_app
from app.web.identity import Identity
from app.web.uploads import CHUNK


def fingerprint(data):
    hashes = "".join(
        hashlib.sha256(data[i : i + CHUNK]).hexdigest() for i in range(0, len(data), CHUNK)
    )
    return hashlib.sha256(hashes.encode()).hexdigest()


def archive():
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("package.json", "{}")
    return out.getvalue()


def manifest(package, audio):
    return {
        "mode": "zip",
        "files": [
            {
                "id": "p0",
                "path": "package.zip",
                "size": len(package),
                "fingerprint": fingerprint(package),
                "role": "package",
            },
            {
                "id": "audio",
                "path": "voice.wav",
                "size": len(audio),
                "fingerprint": fingerprint(audio),
                "role": "audio",
            },
        ],
    }


def put(client, uid, fid, index, data):
    return client.put(
        f"/api/uploads/{uid}/files/{fid}/chunks/{index}",
        content=data,
        headers={"X-Chunk-SHA256": hashlib.sha256(data).hexdigest()},
    )


def test_upload_restart_duplicate_and_integrity(tmp_path):
    settings = replace(
        Settings.from_env(), work_root=tmp_path / "work", export_root=tmp_path / "exports"
    )
    package, audio = archive(), b"audio"
    storage = tmp_path / "storage"
    with TestClient(create_app(settings, storage)) as client:
        created = client.post(
            "/api/uploads", json={"key": "stable-key", "manifest": manifest(package, audio)}
        )
        assert created.status_code == 201, created.text
        uid = created.json()["id"]
        assert (
            client.post(
                "/api/uploads", json={"key": "stable-key", "manifest": manifest(package, audio)}
            ).json()["id"]
            == uid
        )
        assert put(client, uid, "p0", 0, package).status_code == 200
        assert put(client, uid, "p0", 0, package).json()["files"]["p0"] == len(package)
        assert put(client, uid, "p0", 0, b"x").status_code == 422
        assert client.post(f"/api/uploads/{uid}/complete").status_code == 409
    with TestClient(create_app(settings, storage)) as client:
        assert client.get(f"/api/uploads/{uid}").json()["files"]["p0"] == len(package)
        assert put(client, uid, "audio", 0, audio).status_code == 200
        # Server-side corruption is caught before admission.
        (storage / "uploads" / uid / "audio").write_bytes(b"other")
        assert client.post(f"/api/uploads/{uid}/complete").status_code == 422
        assert client.get(f"/api/uploads/{uid}").json()["state"] == "failed"
        assert client.get("/api/jobs/active").json()["id"] is None


def test_upload_bounds_and_auth(tmp_path):
    settings = replace(
        Settings.from_env(), work_root=tmp_path / "work", export_root=tmp_path / "exports"
    )
    from app.web.security import WebGuard

    guard = WebGuard(storage=tmp_path / "storage", max_request_bytes=CHUNK + 1024)
    with RawTestClient(create_app(settings, tmp_path / "storage", guard)) as anonymous:
        assert anonymous.post("/api/uploads", json={}).status_code == 401
        assert anonymous.post("/api/session", json={"token": "secret"}).status_code == 422
    with TestClient(create_app(settings, tmp_path / "storage", guard)) as client:
        package, audio = archive(), b"audio"
        response = client.post(
            "/api/uploads", json={"key": "stable-key", "manifest": manifest(package, audio)}
        )
        assert response.status_code == 201
        uid = response.json()["id"]
        assert put(client, uid, "p0", 1, package).status_code == 422
        assert put(client, uid, "p0", 0, package + b"extra").status_code == 422
        assert (
            client.put(
                f"/api/uploads/{uid}/files/p0/chunks/0",
                content=package,
                headers={"X-Chunk-SHA256": "0" * 64},
            ).status_code
            == 422
        )
        assert (
            client.delete(
                f"/api/uploads/{uid}", headers={"Origin": "https://evil.test"}
            ).status_code
            == 403
        )
        assert client.delete(f"/api/uploads/{uid}").status_code == 200
        assert client.get(f"/api/uploads/{uid}").status_code == 404


def test_completion_is_idempotent_for_zip_and_folder(tmp_path, monkeypatch):
    settings = replace(
        Settings.from_env(),
        work_root=tmp_path / "work",
        export_root=tmp_path / "exports",
        export_min_free_bytes=0,
    )
    monkeypatch.setattr("app.web.uploads.export_root_problem", lambda _: None)
    monkeypatch.setattr("app.web.uploads.validate_audio", lambda *_: None)
    monkeypatch.setattr("app.web.uploads.FinalPackageLoader.load", lambda *_: None)
    monkeypatch.setattr(
        "app.web.jobs.StoryEnginePipeline.generate_bundle",
        lambda self, **_: (_ for _ in ()).throw(RuntimeError("test render stopped")),
    )
    with TestClient(create_app(settings, tmp_path / "storage")) as client:
        for mode in ("zip", "folder"):
            package, audio = archive(), b"audio"
            m = manifest(package, audio)
            if mode == "folder":
                m["mode"] = "folder"
                m["files"][0]["path"] = "root/package.json"
                package = b"{}"
                m["files"][0]["size"] = len(package)
                m["files"][0]["fingerprint"] = fingerprint(package)
            created = client.post("/api/uploads", json={"key": f"key-{mode}-stable", "manifest": m})
            assert created.status_code == 201, created.text
            uid = created.json()["id"]
            assert put(client, uid, "p0", 0, package).status_code == 200
            assert put(client, uid, "audio", 0, audio).status_code == 200
            response = client.post(f"/api/uploads/{uid}/complete")
            assert response.status_code == 202, response.text
            job = response.json()["id"]
            assert f"resumable upload finalized upload={uid} job={job}" in (
                tmp_path / "storage" / "security.log"
            ).read_text(encoding="utf-8")
            assert client.post(f"/api/uploads/{uid}/complete").json()["id"] == job
            assert client.get(f"/api/uploads/{uid}").json()["job_id"] == job
            timings = client.get(f"/api/uploads/{uid}").json()
            assert timings["verify_seconds"] is not None
            assert timings["validation_seconds"] is not None
            assert timings["admitted_at"] is not None
            assert (
                client.get(f"/api/uploads/{uid}").json()["sha256"]["p0"]
                == hashlib.sha256(package).hexdigest()
            )
            # Wait for the deliberately failing test render to release the one-job index.
            import time

            for _ in range(100):
                if client.get(f"/api/jobs/{job}").json()["state"] == "failed":
                    break
                time.sleep(0.01)
            assert client.get(f"/api/jobs/{job}").json()["state"] == "failed"


def test_retry_and_cleanup_do_not_touch_admitted_job(tmp_path, monkeypatch):
    settings = replace(
        Settings.from_env(),
        work_root=tmp_path / "work",
        export_root=tmp_path / "exports",
        export_min_free_bytes=0,
    )
    monkeypatch.setattr("app.web.uploads.export_root_problem", lambda _: None)
    monkeypatch.setattr("app.web.uploads.validate_audio", lambda *_: None)
    monkeypatch.setattr("app.web.uploads.FinalPackageLoader.load", lambda *_: None)
    monkeypatch.setattr(
        "app.web.jobs.StoryEnginePipeline.generate_bundle",
        lambda self, **_: (_ for _ in ()).throw(RuntimeError("test render stopped")),
    )
    storage = tmp_path / "storage"
    package, audio = archive(), b"audio"
    with TestClient(create_app(settings, storage)) as client:
        uid = client.post(
            "/api/uploads", json={"key": "retained-key", "manifest": manifest(package, audio)}
        ).json()["id"]
        assert put(client, uid, "p0", 0, package).status_code == 200
        assert put(client, uid, "audio", 0, audio).status_code == 200
        (storage / "uploads" / uid / "audio").write_bytes(b"other")
        assert client.post(f"/api/uploads/{uid}/complete").status_code == 422
        assert client.post(f"/api/uploads/{uid}/retry").status_code == 200
        assert client.get(f"/api/uploads/{uid}").json()["files"]["p0"] == len(package)
        from app.web.uploads import Uploads
        from app.web.jobs import Jobs

        uploads = Uploads(storage, Jobs(storage, settings), 2 * 1024**3)
        assert uploads.purge_abandoned(0) == 1
        assert client.get(f"/api/uploads/{uid}").status_code == 404


def test_unacknowledged_tail_is_replaced_from_sqlite_offset(tmp_path):
    settings = replace(
        Settings.from_env(), work_root=tmp_path / "work", export_root=tmp_path / "exports"
    )
    package = b"a" * CHUNK + b"b" * CHUNK
    audio = b"audio"
    storage = tmp_path / "storage"
    with TestClient(create_app(settings, storage)) as client:
        uid = client.post(
            "/api/uploads", json={"key": "crash-safe", "manifest": manifest(package, audio)}
        ).json()["id"]
        assert put(client, uid, "p0", 0, package[:CHUNK]).status_code == 200
        import sqlite3

        with sqlite3.connect(storage / "jobs.sqlite3") as db:
            db.execute(
                "UPDATE upload_files SET offset=0 WHERE upload_id=? AND file_id='p0'", (uid,)
            )
            db.execute("DELETE FROM upload_chunks WHERE upload_id=? AND file_id='p0'", (uid,))
        assert put(client, uid, "p0", 0, package[:CHUNK]).status_code == 200
        assert put(client, uid, "p0", 1, package[CHUNK:]).status_code == 200
        assert (storage / "uploads" / uid / "p0").read_bytes() == package
        assert client.get(f"/api/uploads/{uid}").json()["files"]["p0"] == len(package)
        with sqlite3.connect(storage / "jobs.sqlite3") as db:
            assert (
                db.execute(
                    "SELECT COUNT(*) FROM upload_chunks WHERE upload_id=? AND file_id='p0'", (uid,)
                ).fetchone()[0]
                == 2
            )


def test_configured_chunk_size(tmp_path, monkeypatch):
    monkeypatch.setenv("HEXA_WEB_CHUNK_BYTES", str(2 * CHUNK))
    settings = replace(
        Settings.from_env(), work_root=tmp_path / "work", export_root=tmp_path / "exports"
    )
    package = b"a" * (2 * CHUNK)
    audio = b"audio"
    # The fingerprint uses the negotiated slice size.
    digest = hashlib.sha256(hashlib.sha256(package).hexdigest().encode()).hexdigest()
    m = manifest(package, audio)
    m["files"][0]["fingerprint"] = digest
    m["chunk_size"] = 2 * CHUNK
    with TestClient(create_app(settings, tmp_path / "storage")) as client:
        assert client.get("/api/uploads/config").json()["chunk_size"] == 2 * CHUNK
        uid = client.post("/api/uploads", json={"key": "larger-chunk", "manifest": m}).json()["id"]
        assert put(client, uid, "p0", 0, package).status_code == 200
        assert client.get(f"/api/uploads/{uid}").json()["files"]["p0"] == len(package)


def test_disk_preflight_and_rate_limit(tmp_path, monkeypatch):
    settings = replace(
        Settings.from_env(), work_root=tmp_path / "work", export_root=tmp_path / "exports"
    )
    import shutil
    from collections import namedtuple

    usage = namedtuple("usage", "total used free")
    actual = shutil.disk_usage
    monkeypatch.setattr("app.web.uploads.shutil.disk_usage", lambda _: usage(100, 99, 1))
    package, audio = archive(), b"audio"
    with TestClient(create_app(settings, tmp_path / "storage")) as client:
        response = client.post(
            "/api/uploads", json={"key": "disk-low", "manifest": manifest(package, audio)}
        )
        assert response.status_code == 507
    monkeypatch.setattr("app.web.uploads.shutil.disk_usage", actual)
    with TestClient(create_app(settings, tmp_path / "storage2")) as client:
        for i in range(10):
            response = client.post(
                "/api/uploads", json={"key": f"rate-key-{i}", "manifest": manifest(package, audio)}
            )
            assert response.status_code == 201
        assert (
            client.post(
                "/api/uploads", json={"key": "rate-key-last", "manifest": manifest(package, audio)}
            ).status_code
            == 429
        )


def test_invalid_final_package_returns_422_with_retained_inputs(tmp_path, monkeypatch):
    export = tmp_path / "exports"
    export.mkdir()
    settings = replace(
        Settings.from_env(),
        work_root=tmp_path / "work",
        export_root=export,
        export_min_free_bytes=0,
    )
    monkeypatch.setattr("app.web.uploads.validate_audio", lambda *_: None)
    storage = tmp_path / "storage"
    package, audio = archive(), b"audio"
    with TestClient(create_app(settings, storage)) as client:
        uid = client.post(
            "/api/uploads", json={"key": "invalid-package", "manifest": manifest(package, audio)}
        ).json()["id"]
        assert put(client, uid, "p0", 0, package).status_code == 200
        assert put(client, uid, "audio", 0, audio).status_code == 200
        response = client.post(f"/api/uploads/{uid}/complete")
        assert response.status_code == 422, response.text
        state = client.get(f"/api/uploads/{uid}").json()
        assert state["state"] == "failed"
        assert state["sha256"]["p0"] == hashlib.sha256(package).hexdigest()
        assert (storage / "uploads" / uid / "p0").read_bytes() == package


def test_two_uploads_obey_single_render_admission(tmp_path, monkeypatch):
    import threading
    import time

    export = tmp_path / "exports"
    export.mkdir()
    settings = replace(
        Settings.from_env(),
        work_root=tmp_path / "work",
        export_root=export,
        export_min_free_bytes=0,
    )
    monkeypatch.setattr("app.web.uploads.validate_audio", lambda *_: None)
    monkeypatch.setattr("app.web.uploads.FinalPackageLoader.load", lambda *_: None)
    entered = threading.Event()
    release = threading.Event()

    def generate(self, **_):
        entered.set()
        release.wait(10)
        raise RuntimeError("test render stopped")

    monkeypatch.setattr("app.web.jobs.StoryEnginePipeline.generate_bundle", generate)
    package, audio = archive(), b"audio"
    with TestClient(create_app(settings, tmp_path / "storage")) as client:
        ids = []
        for key in ("first-job", "second-job"):
            uid = client.post(
                "/api/uploads", json={"key": key, "manifest": manifest(package, audio)}
            ).json()["id"]
            assert put(client, uid, "p0", 0, package).status_code == 200
            assert put(client, uid, "audio", 0, audio).status_code == 200
            ids.append(uid)
        first = client.post(f"/api/uploads/{ids[0]}/complete")
        assert first.status_code == 202, first.text
        assert entered.wait(10)
        second = client.post(f"/api/uploads/{ids[1]}/complete")
        assert second.status_code == 409
        assert client.get(f"/api/uploads/{ids[1]}").json()["state"] == "uploading"
        release.set()
        for _ in range(100):
            if client.get(f"/api/jobs/{first.json()['id']}").json()["state"] == "failed":
                break
            time.sleep(0.01)
        assert client.post(f"/api/uploads/{ids[1]}/complete").status_code == 202


def test_disk_full_does_not_acknowledge_chunk(tmp_path, monkeypatch):
    import errno
    import os

    settings = replace(
        Settings.from_env(), work_root=tmp_path / "work", export_root=tmp_path / "exports"
    )
    package, audio = archive(), b"audio"
    storage = tmp_path / "storage"
    with TestClient(create_app(settings, storage)) as client:
        uid = client.post(
            "/api/uploads", json={"key": "disk-chunk", "manifest": manifest(package, audio)}
        ).json()["id"]
        original = os.fsync
        monkeypatch.setattr(
            "app.web.uploads.os.fsync",
            lambda _: (_ for _ in ()).throw(OSError(errno.ENOSPC, "full")),
        )
        assert put(client, uid, "p0", 0, package).status_code == 507
        assert client.get(f"/api/uploads/{uid}").json()["files"]["p0"] == 0
        monkeypatch.setattr("app.web.uploads.os.fsync", original)
        assert put(client, uid, "p0", 0, package).status_code == 200


def test_orphan_validation_recovers_without_losing_chunks(tmp_path):
    import sqlite3

    settings = replace(
        Settings.from_env(), work_root=tmp_path / "work", export_root=tmp_path / "exports"
    )
    package, audio = archive(), b"audio"
    storage = tmp_path / "storage"
    with TestClient(create_app(settings, storage)) as client:
        uid = client.post(
            "/api/uploads", json={"key": "orphan-validation", "manifest": manifest(package, audio)}
        ).json()["id"]
        assert put(client, uid, "p0", 0, package).status_code == 200
    with sqlite3.connect(storage / "jobs.sqlite3") as db:
        db.execute(
            "UPDATE uploads SET state='validating',validator_pid=999999999 WHERE id=?", (uid,)
        )
    with TestClient(create_app(settings, storage)) as client:
        state = client.get(f"/api/uploads/{uid}").json()
        assert state["state"] == "uploading"
        assert state["files"]["p0"] == len(package)


def test_failed_job_diagnostics_survive_server_restart(tmp_path, monkeypatch):
    import time
    from app.web.jobs import Jobs

    settings = replace(
        Settings.from_env(), work_root=tmp_path / "work", export_root=tmp_path / "exports"
    )
    storage = tmp_path / "storage"
    jobs = Jobs(storage, settings)
    job_id = jobs.create()
    package = storage / job_id / "package.zip"
    audio = storage / job_id / "audio.wav"
    package.write_bytes(archive())
    audio.write_bytes(b"audio")

    def fail(self, **_):
        raise RuntimeError("test render failure")

    monkeypatch.setattr("app.web.jobs.StoryEnginePipeline.generate_bundle", fail)
    jobs.start(job_id, package, audio)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if jobs.get(job_id)["state"] == "failed":
            break
        time.sleep(0.05)
    assert jobs.get(job_id)["state"] == "failed"
    report_path = storage / job_id / "diagnostics.zip"
    while time.monotonic() < deadline and not report_path.is_file():
        time.sleep(0.05)
    assert report_path.is_file()
    with TestClient(create_app(settings, storage)) as client:
        response = client.get(f"/api/jobs/{job_id}/download/diagnostics")
        assert response.status_code == 200
        assert response.content[:2] == b"PK"


def test_failed_render_retry_uses_retained_inputs(tmp_path, monkeypatch):
    import time
    from app.web.jobs import Jobs

    settings = replace(
        Settings.from_env(), work_root=tmp_path / "work", export_root=tmp_path / "exports"
    )
    storage = tmp_path / "storage"
    jobs = Jobs(storage, settings)
    first = jobs.create()
    package = storage / first / "package.zip"
    audio = storage / first / "audio.wav"
    package.write_bytes(archive())
    audio.write_bytes(b"audio")
    calls = []

    def fail(self, **kwargs):
        calls.append((kwargs["job_id"], kwargs["package_path"], kwargs["audio_path"]))
        raise RuntimeError("test render failure")

    monkeypatch.setattr("app.web.jobs.StoryEnginePipeline.generate_bundle", fail)
    jobs.start(first, package, audio)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline and jobs.get(first)["state"] != "failed":
        time.sleep(0.05)
    assert jobs.get(first)["state"] == "failed"
    with TestClient(create_app(settings, storage)) as client:
        response = client.post(f"/api/jobs/{first}/retry")
        assert response.status_code == 202, response.text
        second = response.json()["id"]
        assert second != first
        while (
            time.monotonic() < deadline
            and client.get(f"/api/jobs/{second}").json()["state"] != "failed"
        ):
            time.sleep(0.05)
        assert client.get(f"/api/jobs/{second}").json()["state"] == "failed"
        assert calls[0][1:] == calls[1][1:] == (package, audio)


def test_zip_duplicate_and_dot_segments_rejected(tmp_path):
    import pytest
    from fastapi import HTTPException
    from app.web.validation import validate_zip

    path = tmp_path / "unsafe.zip"
    for names in [("root/a", "root/A"), ("root/./file",), ("root/..",)]:
        with zipfile.ZipFile(path, "w") as archive:
            for name in names:
                archive.writestr(name, b"x")
        with pytest.raises(HTTPException) as exc:
            validate_zip(path)
        assert exc.value.status_code == 422


def test_resumable_manifest_rejects_traversal_and_duplicate_paths(tmp_path):
    settings = replace(
        Settings.from_env(), work_root=tmp_path / "work", export_root=tmp_path / "exports"
    )
    package, audio = archive(), b"audio"
    with TestClient(create_app(settings, tmp_path / "storage")) as client:
        for unsafe in (
            "../escape.zip",
            "/absolute.zip",
            "C:/drive.zip",
            "root/./file.zip",
            "root\\file.zip",
        ):
            m = manifest(package, audio)
            m["files"][0]["path"] = unsafe
            response = client.post("/api/uploads", json={"key": "unsafe-path-key", "manifest": m})
            assert response.status_code == 422, (unsafe, response.text)
        m = manifest(package, audio)
        m["mode"] = "folder"
        m["files"][0]["path"] = "root/File.json"
        m["files"].insert(1, {**m["files"][0], "id": "p1", "path": "root/file.json"})
        assert (
            client.post(
                "/api/uploads", json={"key": "duplicate-path-key", "manifest": m}
            ).status_code
            == 422
        )


def test_aggregate_upload_reservation_limit(tmp_path, monkeypatch):
    package, audio = archive(), b"audio"
    monkeypatch.setenv("HEXA_WEB_TOTAL_UPLOAD_BYTES", str(len(package) + len(audio) + 1))
    settings = replace(
        Settings.from_env(), work_root=tmp_path / "work", export_root=tmp_path / "exports"
    )
    with TestClient(create_app(settings, tmp_path / "storage")) as client:
        assert (
            client.post(
                "/api/uploads",
                json={"key": "reservation-one", "manifest": manifest(package, audio)},
            ).status_code
            == 201
        )
        assert (
            client.post(
                "/api/uploads",
                json={"key": "reservation-two", "manifest": manifest(package, audio)},
            ).status_code
            == 429
        )


def test_chunk_fs_operation_does_not_block_health(tmp_path, monkeypatch):
    """A delayed disk commit must not block the ASGI event loop."""
    import asyncio
    import threading

    import httpx
    from app.web.uploads import Uploads

    async def exercise():
        settings = replace(
            Settings.from_env(),
            work_root=tmp_path / "work",
            export_root=tmp_path / "exports",
        )
        entered = threading.Event()
        release = threading.Event()
        original = Uploads._commit_chunk

        def delayed_commit(self, *args):
            entered.set()
            if not release.wait(10):
                raise RuntimeError("test commit was not released")
            return original(self, *args)

        monkeypatch.setattr(Uploads, "_commit_chunk", delayed_commit)
        app = create_app(settings, tmp_path / "storage")
        Identity(tmp_path / "storage" / "jobs.sqlite3").bootstrap()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            auth = await client.post("/api/session", json={"email": os.environ["HEXA_ADMIN_EMAIL"],
                                                           "password": os.environ["HEXA_ADMIN_BOOTSTRAP_PASSWORD"]})
            assert auth.status_code == 200
            csrf = auth.json()["csrf"]
            package, audio = archive(), b"audio"
            response = await client.post(
                "/api/uploads",
                json={"key": "responsive-upload-key", "manifest": manifest(package, audio)},
                headers={"X-CSRF-Token": csrf},
            )
            assert response.status_code == 201, response.text
            uid = response.json()["id"]
            pending = asyncio.create_task(
                client.put(
                    f"/api/uploads/{uid}/files/p0/chunks/0",
                    content=package,
                    headers={"X-Chunk-SHA256": hashlib.sha256(package).hexdigest(), "X-CSRF-Token": csrf},
                )
            )
            try:
                assert await asyncio.to_thread(entered.wait, 5)
                health = await asyncio.wait_for(client.get("/health"), timeout=2)
                assert health.status_code == 200
            finally:
                release.set()
            assert (await pending).status_code == 200

    asyncio.run(exercise())


def test_upload_cannot_be_discarded_during_validation(tmp_path, monkeypatch):
    """Explicit discard cannot delete inputs a finalizer is currently validating."""
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from fastapi import HTTPException

    settings = replace(
        Settings.from_env(),
        work_root=tmp_path / "work",
        export_root=tmp_path / "exports",
        export_min_free_bytes=0,
    )
    monkeypatch.setattr("app.web.uploads.export_root_problem", lambda _: None)
    entered = threading.Event()
    release = threading.Event()

    def delayed_audio(*_args):
        entered.set()
        if not release.wait(10):
            raise RuntimeError("validation test not released")
        raise HTTPException(status_code=422, detail="Intentional test validation failure")

    monkeypatch.setattr("app.web.uploads.validate_audio", delayed_audio)
    package, audio = archive(), b"audio"
    storage = tmp_path / "storage"
    with TestClient(create_app(settings, storage)) as client:
        initialized = client.post(
            "/api/uploads",
            json={"key": "validation-delete-race", "manifest": manifest(package, audio)},
        )
        assert initialized.status_code == 201, initialized.text
        uid = initialized.json()["id"]
        assert put(client, uid, "p0", 0, package).status_code == 200
        assert put(client, uid, "audio", 0, audio).status_code == 200
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(client.post, f"/api/uploads/{uid}/complete")
            try:
                assert entered.wait(5), "Validation did not start"
                rejected = client.delete(f"/api/uploads/{uid}")
                assert rejected.status_code == 409
                assert (storage / "uploads" / uid / "p0").is_file()
            finally:
                release.set()
            result = future.result(timeout=10)
            assert result.status_code == 422
            assert client.get(f"/api/uploads/{uid}").json()["state"] == "failed"

def test_v2_four_mib_chunk_acknowledges_durable_progress(tmp_path, monkeypatch):
    monkeypatch.setenv("HEXA_WEB_V2_ENABLED", "1")
    settings = replace(
        Settings.from_env(), work_root=tmp_path / "work", export_root=tmp_path / "exports"
    )
    package = b"z" * (4 * 1024 * 1024 + 17)
    audio = b"audio"
    m = manifest(package, audio)
    m["protocol"] = 2
    m["chunk_size"] = 4 * 1024 * 1024
    m["files"][0]["fingerprint"] = hashlib.sha256(
        (hashlib.sha256(package[:4 * 1024 * 1024]).hexdigest()
         + hashlib.sha256(package[4 * 1024 * 1024:]).hexdigest()).encode()
    ).hexdigest()
    storage = tmp_path / "storage"
    with TestClient(create_app(settings, storage)) as client:
        config = client.get("/api/uploads/config").json()
        assert config["v2_chunk_size"] == 4 * 1024 * 1024
        created = client.post("/api/uploads", json={"key": "v2-four-mib", "manifest": m})
        assert created.status_code == 201, created.text
        uid = created.json()["id"]
        first = put(client, uid, "p0", 0, package[:4 * 1024 * 1024])
        assert first.status_code == 200, first.text
        assert first.json()["files"]["p0"] == 4 * 1024 * 1024
        assert put(client, uid, "p0", 0, package[:4 * 1024 * 1024]).json()["files"]["p0"] == 4 * 1024 * 1024
        assert put(client, uid, "p0", 1, package[4 * 1024 * 1024:]).status_code == 200
        assert put(client, uid, "audio", 0, audio).status_code == 200
        assert (storage / "uploads" / uid / "p0").read_bytes() == package


def test_v1_idempotent_resume_survives_server_default_change(tmp_path, monkeypatch):
    settings = replace(
        Settings.from_env(), work_root=tmp_path / "work", export_root=tmp_path / "exports"
    )
    storage = tmp_path / "storage"
    package, audio = archive(), b"audio"
    m = manifest(package, audio)
    with TestClient(create_app(settings, storage)) as client:
        created = client.post("/api/uploads", json={"key": "v1-old-default", "manifest": m})
        assert created.status_code == 201
        uid = created.json()["id"]
    monkeypatch.setenv("HEXA_WEB_CHUNK_BYTES", str(2 * CHUNK))
    with TestClient(create_app(settings, storage)) as client:
        resumed = client.post("/api/uploads", json={"key": "v1-old-default", "manifest": m})
        assert resumed.status_code == 201, resumed.text
        assert resumed.json()["id"] == uid
        assert resumed.json()["chunk_size"] == CHUNK
        assert put(client, uid, "p0", 0, package).status_code == 200

def test_v2_rejects_out_of_order_conflict_and_oversize(tmp_path, monkeypatch):
    monkeypatch.setenv("HEXA_WEB_V2_ENABLED", "1")
    settings = replace(
        Settings.from_env(), work_root=tmp_path / "work", export_root=tmp_path / "exports"
    )
    chunk = 4 * 1024 * 1024
    package, audio = b"q" * (chunk + 1), b"audio"
    m = manifest(package, audio)
    m.update(protocol=2, chunk_size=chunk)
    m["files"][0]["fingerprint"] = hashlib.sha256(
        (hashlib.sha256(package[:chunk]).hexdigest()
         + hashlib.sha256(package[chunk:]).hexdigest()).encode()
    ).hexdigest()
    with TestClient(create_app(settings, tmp_path / "storage")) as client:
        uid = client.post("/api/uploads", json={"key": "v2-conflict", "manifest": m}).json()["id"]
        assert put(client, uid, "p0", 1, package[chunk:]).status_code == 409
        assert put(client, uid, "p0", 0, package + b"x").status_code == 413
        assert put(client, uid, "p0", 0, package[:chunk]).status_code == 200
        assert put(client, uid, "p0", 0, b"x" * chunk).status_code == 409
        assert client.get(f"/api/uploads/{uid}").json()["files"]["p0"] == chunk

def test_v2_flag_disables_new_sessions_but_keeps_existing(tmp_path, monkeypatch):
    settings = replace(
        Settings.from_env(), work_root=tmp_path / "work", export_root=tmp_path / "exports"
    )
    storage = tmp_path / "storage"
    package, audio = archive(), b"audio"
    m = manifest(package, audio)
    m.update(protocol=2, chunk_size=4 * 1024 * 1024)
    m["files"][0]["fingerprint"] = hashlib.sha256(
        hashlib.sha256(package).hexdigest().encode()
    ).hexdigest()
    monkeypatch.setenv("HEXA_WEB_V2_ENABLED", "1")
    with TestClient(create_app(settings, storage)) as client:
        created = client.post("/api/uploads", json={"key": "v2-before-rollback", "manifest": m})
        assert created.status_code == 201, created.text
        uid = created.json()["id"]
    monkeypatch.delenv("HEXA_WEB_V2_ENABLED")
    with TestClient(create_app(settings, storage)) as client:
        assert client.get("/api/uploads/config").json()["protocols"] == [1]
        resumed = client.post("/api/uploads", json={"key": "v2-before-rollback", "manifest": m})
        assert resumed.status_code == 201
        assert resumed.json()["id"] == uid
        assert put(client, uid, "p0", 0, package).status_code == 200
        assert client.post("/api/uploads", json={"key": "new-v2-disabled", "manifest": m}).status_code == 409

def test_v2_real_package_and_wav_reach_job_admission(tmp_path, monkeypatch):
    import wave
    from tests.support.unified_package import write_unified_package

    monkeypatch.setenv("HEXA_WEB_V2_ENABLED", "1")
    package_dir = write_unified_package(
        tmp_path / "fixture", script="One visual idea.",
        scenes=[{"scene_id": "s1", "script_span": {"text": "One visual idea.",
                 "global_char_start": 0, "global_char_end": 16},
                 "assets": [{"asset_id": "a1", "role": "primary",
                             "script_text": "One visual idea.",
                             "script_span": {"text": "One visual idea.",
                                             "global_char_start": 0, "global_char_end": 16},
                             "binding_type": "EXPLICIT"}]}],
    )
    zip_path = tmp_path / "valid.zip"
    with zipfile.ZipFile(zip_path, "w") as bundle:
        for source in package_dir.rglob("*"):
            if source.is_file():
                bundle.write(source, "package/" + source.relative_to(package_dir).as_posix())
    wav_path = tmp_path / "voice.wav"
    with wave.open(str(wav_path), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(16000)
        stream.writeframes(b"\0\0" * 32000)
    package, audio = zip_path.read_bytes(), wav_path.read_bytes()
    m = manifest(package, audio)
    m.update(protocol=2, chunk_size=4 * 1024 * 1024)
    m["files"][0]["fingerprint"] = hashlib.sha256(
        hashlib.sha256(package).hexdigest().encode()
    ).hexdigest()
    m["files"][1]["fingerprint"] = hashlib.sha256(
        hashlib.sha256(audio).hexdigest().encode()
    ).hexdigest()
    export = tmp_path / "exports"
    export.mkdir()
    settings = replace(Settings.from_env(), work_root=tmp_path / "work",
                       export_root=export, export_min_free_bytes=0)
    started = []
    monkeypatch.setattr("app.web.jobs.Jobs.start", lambda self, *args: started.append(args))
    with TestClient(create_app(settings, tmp_path / "storage")) as client:
        created = client.post("/api/uploads", json={"key": "v2-real-validation", "manifest": m})
        assert created.status_code == 201, created.text
        uid = created.json()["id"]
        assert put(client, uid, "p0", 0, package).status_code == 200
        assert put(client, uid, "audio", 0, audio).status_code == 200
        admitted = client.post(f"/api/uploads/{uid}/complete")
        assert admitted.status_code == 202, admitted.text
        assert client.get(f"/api/uploads/{uid}").json()["job_id"] == admitted.json()["id"]
        assert len(started) == 1
