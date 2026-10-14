from __future__ import annotations

import io
import threading
import time
import zipfile
from dataclasses import replace
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.config import Settings
from app.models import Stage
from app.web.server import create_app
from app.web.jobs import Jobs
from app.web.validation import validate_zip


def archive(name="package.json", content=b"{}"):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as output:
        output.writestr(name, content)
    return stream.getvalue()


def test_zip_boundary(tmp_path):
    path = tmp_path / "package.zip"
    for name in ("../escape", "/absolute", "C:/drive"):
        path.write_bytes(archive(name))
        with pytest.raises(HTTPException):
            validate_zip(path)
    path.write_bytes(b"not a ZIP")
    with pytest.raises(HTTPException):
        validate_zip(path)
    path.write_bytes(archive())
    validate_zip(path)


def test_frontend_and_job_lifecycle(tmp_path, monkeypatch):
    settings = replace(Settings.from_env(), work_root=tmp_path / "work",
                       export_root=tmp_path / "exports", export_min_free_bytes=0)
    monkeypatch.setattr("app.web.server.export_root_problem", lambda _: None)
    monkeypatch.setattr("app.web.server.validate_audio", lambda *_: None)
    monkeypatch.setattr("app.web.server.FinalPackageLoader.load", lambda *_: None)
    called = []

    def generate(self, *, package_path, audio_path, job_id, progress, cancelled):
        called.append((package_path, audio_path, job_id, cancelled))
        progress(Stage.input, 0.5, "Real callback message")
        bundle = tmp_path / "exports" / "PKG" / "v1"
        bundle.mkdir(parents=True)
        youtube = bundle / "youtube.mp4"
        reels = bundle / "reels.mp4"
        youtube.write_bytes(b"youtube")
        reels.write_bytes(b"reels")
        (bundle / "export.json").write_text("{}")
        return SimpleNamespace(directory=bundle, youtube=SimpleNamespace(path=youtube),
                               reels=SimpleNamespace(path=reels))

    monkeypatch.setattr("app.web.jobs.StoryEnginePipeline.generate_bundle", generate)
    with TestClient(create_app(settings, tmp_path / "storage")) as client:
        assert client.get("/").status_code == 200
        assert "HEXA StoryEngine" in client.get("/").text
        assert client.get("/health").json()["ok"]
        response = client.post("/api/jobs", files={"package": ("test.zip", archive()),
                                                       "audio": ("voice.wav", b"audio")})
        assert response.status_code == 202, response.text
        job_id = response.json()["id"]
        for _ in range(100):
            state = client.get(f"/api/jobs/{job_id}").json()
            if state["state"] == "completed":
                break
            time.sleep(0.01)
        assert state["state"] == "completed"
        assert called[0][2] == job_id
        assert called[0][0].parent == tmp_path / "storage" / job_id
        assert "Real callback message" in str(client.get(f"/api/jobs/{job_id}/events").json())
        assert client.get(f"/api/jobs/{job_id}/download/youtube").content == b"youtube"
        assert client.get(f"/api/jobs/{job_id}/download/reels").content == b"reels"
        assert client.get(f"/api/jobs/{job_id}/download/../../etc").status_code != 200


def test_single_active_job_and_cancellation(tmp_path, monkeypatch):
    settings = replace(Settings.from_env(), work_root=tmp_path / "work",
                       export_root=tmp_path / "exports")
    jobs = Jobs(tmp_path / "storage", settings)
    first = jobs.create()
    assert first
    assert jobs.create() is None
    entered = threading.Event()

    def generate(self, *, cancelled, progress, **kwargs):
        entered.set()
        while not cancelled():
            time.sleep(0.01)
        from app.shared.errors import GenerationCancelledError
        raise GenerationCancelledError("cancelled")

    monkeypatch.setattr("app.web.jobs.StoryEnginePipeline.generate_bundle", generate)
    package = jobs.root / first / "package.zip"
    audio = jobs.root / first / "audio.wav"
    package.write_bytes(archive())
    audio.write_bytes(b"audio")
    jobs.start(first, package, audio)
    assert entered.wait(10)
    assert jobs.cancel(first)
    assert jobs.get(first)["state"] in {"cancelling", "canceled"}
    for _ in range(100):
        if jobs.get(first)["state"] == "canceled":
            break
        time.sleep(0.01)
    assert jobs.get(first)["state"] == "canceled"
    assert jobs.create() is not None


def test_invalid_upload_and_failed_worker(tmp_path, monkeypatch):
    settings = replace(Settings.from_env(), work_root=tmp_path / "work",
                       export_root=tmp_path / "exports")
    monkeypatch.setattr("app.web.server.export_root_problem", lambda _: None)
    monkeypatch.setattr("app.web.server.validate_audio", lambda *_: None)
    monkeypatch.setattr("app.web.server.FinalPackageLoader.load", lambda *_: None)

    def fail(self, **kwargs):
        raise RuntimeError("Engine error")

    monkeypatch.setattr("app.web.jobs.StoryEnginePipeline.generate_bundle", fail)
    with TestClient(create_app(settings, tmp_path / "storage")) as client:
        invalid = client.post("/api/jobs", files={"package": ("test.zip", b"invalid"),
                                                     "audio": ("voice.wav", b"audio")})
        assert invalid.status_code == 422
        response = client.post("/api/jobs", files={"package": ("test.zip", archive()),
                                                      "audio": ("voice.wav", b"audio")})
        assert response.status_code == 202
        job_id = response.json()["id"]
        for _ in range(100):
            state = client.get(f"/api/jobs/{job_id}").json()
            if state["state"] == "failed":
                break
            time.sleep(0.01)
        assert state["state"] == "failed"
        assert "Engine error" in state["message"]
        assert client.get(f"/api/jobs/{job_id}/download/youtube").status_code == 404
