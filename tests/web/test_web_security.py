"""Web production guards: same-origin writes, access token, limits, readiness, retention."""
from __future__ import annotations

import os
import time
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from tests.web.auth_client import AuthenticatedTestClient

from app.config import Settings
from app.web.jobs import Jobs
from app.web.security import SESSION_COOKIE, WebGuard, is_loopback
from app.web.server import create_app


def _settings(tmp_path):
    return replace(Settings.from_env(), work_root=tmp_path / "work",
                   export_root=tmp_path / "exports", export_min_free_bytes=0)


def _client(tmp_path, *, anonymous=False, max_request=10_000_000, hosts=None):
    storage = tmp_path / "storage"
    guard = WebGuard(storage=storage, max_request_bytes=max_request, allowed_hosts=hosts)
    cls = TestClient if anonymous else AuthenticatedTestClient
    return cls(create_app(_settings(tmp_path), storage, guard=guard)), storage


def test_cross_site_writes_are_refused_and_logged(tmp_path):
    client, storage = _client(tmp_path)
    with client:
        assert client.post("/api/jobs/x/cancel", headers={"Origin": "https://evil.example"}).status_code == 403
        assert client.post("/api/jobs/x/cancel", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
        same = client.post("/api/jobs/x/cancel", headers={"Origin": "http://testserver"})
        assert same.status_code == 404                                   # reaches the route
    assert "refused cross-origin" in (storage / "security.log").read_text(encoding="utf-8")


def test_unknown_host_is_refused_against_dns_rebinding(tmp_path):
    client, _storage = _client(tmp_path)
    with client:
        assert client.get("/api/jobs/active", headers={"Host": "attacker.example"}).status_code == 421
        assert client.get("/api/jobs/active").status_code == 200


def test_account_authentication_protects_the_api_and_downloads(tmp_path):
    client, storage = _client(tmp_path, anonymous=True)
    with client:
        assert client.get("/").status_code == 200                       # the page itself loads
        assert client.get("/health").status_code == 200
        assert client.get("/api/session").json()["authenticated"] is False
        assert client.get("/api/jobs/active").status_code == 401
        assert client.get("/api/jobs/x/download/youtube").status_code == 401
        assert client.post("/api/session", json={"token": "s3cret-token"}).status_code == 422
        import os
        login = client.post("/api/session", json={"email": os.environ["HEXA_ADMIN_EMAIL"],
                                                   "password": os.environ["HEXA_ADMIN_BOOTSTRAP_PASSWORD"]})
        assert login.status_code == 200 and SESSION_COOKIE in login.cookies
        assert client.get("/api/jobs/active").status_code == 200        # cookie session
    other, _ = _client(tmp_path / "b", anonymous=True)
    with other:
        assert other.get("/api/jobs/active", headers={"Authorization": "Bearer s3cret-token"}).status_code == 401
    log = (storage / "security.log").read_text(encoding="utf-8")
    assert "s3cret-token" not in log


def test_oversized_request_is_refused_before_the_upload_is_read(tmp_path):
    client, _storage = _client(tmp_path, max_request=1000)
    with client:
        response = client.post("/api/jobs", files={"audio": ("a.wav", b"x" * 5000)})
        assert response.status_code == 413


def test_security_headers_on_every_response(tmp_path):
    client, _storage = _client(tmp_path)
    with client:
        headers = client.get("/").headers
        assert headers["x-frame-options"] == "DENY" and headers["x-content-type-options"] == "nosniff"
        assert "frame-ancestors 'none'" in headers["content-security-policy"]


def test_readiness_reports_concrete_problems(tmp_path, monkeypatch):
    client, _storage = _client(tmp_path)
    monkeypatch.setattr("app.web.server.export_root_problem", lambda _: "export root missing")
    with client:
        response = client.get("/ready")
        assert response.status_code == 503
        assert any(row.startswith("export_root:") for row in response.json()["problems"])



def test_deployment_maintenance_blocks_mutations_but_keeps_reads_and_headers(tmp_path):
    client, storage = _client(tmp_path)
    with client:
        marker = storage / ".deploy-maintenance"
        marker.write_text("deployment", encoding="utf-8")
        response = client.post("/api/jobs/missing/cancel")
        assert response.status_code == 503
        assert response.headers["retry-after"] == "45"
        assert response.headers["x-frame-options"] == "DENY"
        assert client.get("/api/jobs/active").status_code == 200
        assert client.get("/health").status_code == 200
        marker.unlink()
        assert client.post("/api/jobs/missing/cancel").status_code == 404


def test_retention_removes_only_old_finished_uploads(tmp_path):
    settings = _settings(tmp_path)
    jobs = Jobs(tmp_path / "storage", settings)
    done, running = jobs.create(), None
    jobs.update(done, state="completed")
    old = time.time() - 10 * 86400
    os.utime(jobs.root / done, (old, old))
    keep = jobs.root / "not-a-job"
    keep.mkdir()
    os.utime(keep, (old, old))
    assert Jobs(tmp_path / "storage", settings, retention_days=7).root == jobs.root
    assert not (jobs.root / done).exists() and keep.exists()
    assert running is None


@pytest.mark.parametrize("host,expected", [("127.0.0.1", True), ("localhost", True), ("::1", True),
                                           ("0.0.0.0", False), ("192.168.1.5", False)])
def test_loopback_detection_for_the_bind_guard(host, expected):
    assert is_loopback(host) is expected
