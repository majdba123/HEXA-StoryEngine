"""The operator's soundtrack switches (sound effects, background music) on the web panel.

The page sends them when it completes an upload (the job starts then); the job runs with
them, a retry keeps them, and a client that sends nothing keeps the server's defaults.
"""
from __future__ import annotations

import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.config import Settings
from app.web.jobs import Jobs, generation_options, sound_options
from app.web.server import create_app
from tests.web.auth_client import AuthenticatedTestClient as TestClient
from tests.web.test_uploads import archive, manifest, put

STATIC = Path(__file__).resolve().parents[2] / "app" / "web" / "static"


def _settings(tmp_path: Path) -> Settings:
    return replace(Settings.from_env(), work_root=tmp_path / "work", export_root=tmp_path / "exports",
                   export_min_free_bytes=0)


def _run_upload(tmp_path: Path, monkeypatch, body: dict | None,
                expected_kind: str = "VIDEO") -> Settings:
    seen: list[tuple[str, Settings]] = []

    def generate_video(self, **_):
        seen.append(("VIDEO", self.settings))
        raise RuntimeError("test render stopped")

    def generate_premiere(self, **_):
        seen.append(("PREMIERE", self.settings))
        raise RuntimeError("test render stopped")

    monkeypatch.setattr("app.web.uploads.export_root_problem", lambda _: None)
    monkeypatch.setattr("app.web.uploads.validate_audio", lambda *_: None)
    monkeypatch.setattr("app.web.uploads.FinalPackageLoader.load", lambda *_: None)
    monkeypatch.setattr("app.web.jobs.StoryEnginePipeline.generate_bundle", generate_video)
    monkeypatch.setattr("app.web.jobs.StoryEnginePipeline.generate_premiere", generate_premiere)
    with TestClient(create_app(_settings(tmp_path), tmp_path / "storage")) as client:
        config = client.get("/api/uploads/config").json()
        assert config["sound_effects"] is True and config["background_music"] is True
        package, audio = archive(), b"audio"
        uid = client.post("/api/uploads", json={"key": "key-sound-switch", "manifest": manifest(package, audio)}).json()["id"]
        assert put(client, uid, "p0", 0, package).status_code == 200
        assert put(client, uid, "audio", 0, audio).status_code == 200
        response = client.post(f"/api/uploads/{uid}/complete", **({"json": body} if body is not None else {}))
        assert response.status_code == 202, response.text
        job = response.json()["id"]
        for _ in range(300):
            if client.get(f"/api/jobs/{job}").json()["state"] == "failed":
                break
            time.sleep(0.01)
    assert len(seen) == 1
    assert seen[0][0] == expected_kind
    return seen[0][1]


def test_the_web_switches_reach_the_engine(tmp_path, monkeypatch) -> None:
    settings = _run_upload(tmp_path, monkeypatch, {"sound_effects": False, "background_music": False})
    assert settings.sound_effects is False and settings.background_music is False


def test_a_client_that_sends_no_switches_keeps_the_server_defaults(tmp_path, monkeypatch) -> None:
    settings = _run_upload(tmp_path, monkeypatch, None)
    assert settings.sound_effects is True and settings.background_music is True


def test_premiere_choice_reaches_the_real_worker_branch(tmp_path, monkeypatch) -> None:
    settings = _run_upload(tmp_path, monkeypatch, {"output_kind": "PREMIERE",
                                                  "sound_effects": False}, "PREMIERE")
    assert settings.sound_effects is False


def test_only_real_boolean_switches_are_accepted() -> None:
    assert sound_options({"sound_effects": False, "background_music": "no", "export_root": "C:/"}) == {
        "sound_effects": False}
    assert sound_options(["sound_effects"]) == {}
    with pytest.raises(ValueError, match="output kind"):
        generation_options({"output_kind": "NOT_SUPPORTED"})


def test_a_job_remembers_its_switches_for_a_retry(tmp_path, monkeypatch) -> None:
    jobs = Jobs(tmp_path / "storage", _settings(tmp_path))
    monkeypatch.setattr(Jobs, "_run", lambda *args: None)
    jobs.start("job1", tmp_path / "p.zip", tmp_path / "a.wav", {"background_music": False})
    assert jobs.options_for("job1") == {"background_music": False}
    assert jobs.options_for("missing") == {}
    jobs.start("job2", tmp_path / "p.zip", tmp_path / "a.wav", {"output_kind": "PREMIERE"})
    assert jobs.options_for("job2") == {"output_kind": "PREMIERE"}


def test_completed_premiere_job_records_project_paths(tmp_path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    jobs = Jobs(tmp_path / "storage", settings)
    bundle = tmp_path / "exports" / "EDITABLE" / "v1"
    bundle.mkdir(parents=True)
    manifest_path = bundle / "export.json"
    manifest_path.write_text("{}", encoding="utf-8")
    youtube = bundle / "EDITABLE_YOUTUBE_PREMIERE.xml"
    reels = bundle / "EDITABLE_REELS_PREMIERE.xml"
    youtube.write_text("<xmeml/>", encoding="utf-8")
    reels.write_text("<xmeml/>", encoding="utf-8")

    def generate(self, **_):
        return SimpleNamespace(directory=bundle, manifest_path=manifest_path,
                               youtube=SimpleNamespace(path=youtube),
                               reels=SimpleNamespace(path=reels))

    monkeypatch.setattr("app.web.jobs.StoryEnginePipeline.generate_premiere", generate)
    monkeypatch.setattr("app.web.jobs.StoryEnginePipeline.generate_bundle",
                        lambda *args, **kwargs: pytest.fail("Video generation was selected"))
    monkeypatch.setattr(jobs, "save_report", lambda *args: None)
    job_id = jobs.create(package_name="EDITABLE")
    assert job_id is not None
    jobs.start(job_id, tmp_path / "package.zip", tmp_path / "audio.wav",
               {"output_kind": "PREMIERE"})
    for _ in range(300):
        if jobs.get(job_id)["state"] in {"completed", "failed"}:
            break
        time.sleep(0.01)
    result = jobs.get(job_id)
    assert result["state"] == "completed", result["message"]
    assert result["bundle"] == str(bundle)
    assert result["youtube"] == str(youtube)
    assert result["reels"] == str(reels)


def test_the_page_offers_both_switches() -> None:
    page = (STATIC / "index.html").read_text(encoding="utf-8")
    script = (STATIC / "app.js").read_text(encoding="utf-8")
    assert 'id="sound-effects" type="checkbox"' in page and "مؤثرات صوتية" in page
    assert 'id="background-music" type="checkbox"' in page and "موسيقى خلفية" in page
    assert script.count("/complete`, completion())") == 2  # both completion paths send them
    assert 'name="output-kind" value="PREMIERE"' in page
    assert 'output_kind:lockedOutputKind()' in script


def test_intro_zoom_web_controls_and_complete_manifest() -> None:
    page = (STATIC / "index.html").read_text(encoding="utf-8")
    intro = (STATIC / "intro-zoom.js").read_text(encoding="utf-8")
    script = (STATIC / "app.js").read_text(encoding="utf-8")
    assert 'id="intro-enabled"' in page
    assert 'id="intro-image-area"' in page
    assert 'id="intro-voice"' in page
    assert "/static/intro-zoom.js" in page
    assert "focus_x" in intro and "focus_y" in intro and "magnification" in intro
    assert "introSelection" in script and "intro_zoom" in script
    assert "window.HEXAIntroZoom.files" in script


def test_intro_selection_validation() -> None:
    from app.web.intro_zoom import selection
    assert selection({"focus_x": 0.25, "focus_y": 0.6, "magnification": 2.5}) == {
        "focus_x": 0.25, "focus_y": 0.6, "magnification": 2.5}
    for bad in ({"focus_x": -0.1, "focus_y": 0.6, "magnification": 2.5},
                {"focus_x": 0.2, "focus_y": 0.6, "magnification": 9},
                {"focus_x": "0.2", "focus_y": 0.6, "magnification": 2.5},
                {"focus_x": 0.2, "focus_y": 0.6, "magnification": float("nan")}):
        with pytest.raises(ValueError):
            selection(bad)


def test_intro_invalid_role_pairs_rejected(tmp_path) -> None:
    from fastapi import HTTPException
    from app.web.uploads import Uploads
    settings = _settings(tmp_path)
    jobs = Jobs(tmp_path / "storage", settings)
    uploads = Uploads(tmp_path / "storage", jobs, 20 * 1024 * 1024)
    initial = manifest(archive(), b"audio")
    selected = {"focus_x": 0.5, "focus_y": 0.5, "magnification": 2.5}
    initial["intro_zoom"] = selected
    with pytest.raises(HTTPException) as issue:
        uploads.initialize("test-user", "intro-missing-role", initial)
    assert issue.value.status_code == 413
    initial["files"].append({"id":"intro_image","path":"board.png","size":100,
                             "fingerprint":"a"*64,"role":"intro_image"})
    with pytest.raises(HTTPException) as issue:
        uploads.initialize("test-user", "intro-missing-voice", initial)
    assert issue.value.status_code == 413
    initial["files"].append({"id":"intro_audio","path":"short.wav","size":100,
                             "fingerprint":"b"*64,"role":"intro_audio"})
    accepted = uploads.initialize("test-user", "intro-complete-roles", initial)
    assert accepted["manifest"]["intro_zoom"] == selected
    initial["intro_zoom"]["focus_x"] = float("nan")
    with pytest.raises(HTTPException) as issue:
        uploads.initialize("test-user", "intro-bad-coordinates", initial)
    assert issue.value.status_code == 422


def test_intro_web_preflight_and_retry_reuses_validated_media(tmp_path, monkeypatch) -> None:
    from PIL import Image
    from app.web.intro_zoom import from_job, prepare
    from app.features.intro_zoom.models import IntroZoomConfig

    directory = tmp_path / "upload"
    directory.mkdir()
    original_image = directory / "source.png"
    original_voice = directory / "clip.wav"
    Image.new("RGB", (180, 180), "white").save(original_image)
    original_voice.write_bytes(b"test-audio")
    called = []

    def fake_preflight(config: IntroZoomConfig, **kwargs):
        called.append(config)
        return None

    monkeypatch.setattr("app.web.intro_zoom.preflight", fake_preflight)
    choice = {"focus_x": 0.5, "focus_y": 0.3, "magnification": 3.0}
    prepared = prepare(directory, original_image, original_voice, choice)
    assert prepared.image == directory / "intro-image.png"
    assert prepared.audio == directory / "intro-voice.wav"
    assert called == [prepared]
    assert from_job(directory / "package.zip", choice) == prepared
    with pytest.raises(ValueError):
        from_job(tmp_path / "other" / "package.zip", choice)


def test_resumable_intro_upload_reaches_video_engine(tmp_path, monkeypatch) -> None:
    """Real chunk protocol, image/voice staging, saved choice and worker handoff."""
    import io

    from PIL import Image
    from app.features.intro_zoom.models import IntroZoomConfig
    from tests.web.test_uploads import fingerprint

    captured = []

    def generate(self, **kwargs):
        captured.append(kwargs.get("intro_zoom"))
        raise RuntimeError("intentional stop after intro handoff")

    monkeypatch.setattr("app.web.uploads.export_root_problem", lambda _: None)
    monkeypatch.setattr("app.web.uploads.validate_audio", lambda *_: None)
    monkeypatch.setattr("app.web.uploads.FinalPackageLoader.load", lambda *_: None)
    monkeypatch.setattr("app.web.intro_zoom.preflight", lambda *args, **kwargs: None)
    monkeypatch.setattr("app.web.jobs.StoryEnginePipeline.generate_bundle", generate)
    with TestClient(create_app(_settings(tmp_path), tmp_path / "storage")) as client:
        package, narration = archive(), b"narration"
        data = io.BytesIO()
        Image.new("RGB", (160, 160), "#fff").save(data, format="PNG")
        image = data.getvalue()
        voice = b"short-voice"
        selected = {"focus_x": 0.51, "focus_y": 0.26, "magnification": 3.1}
        upload = manifest(package, narration)
        upload["intro_zoom"] = selected
        upload["files"] += [
            {"id": "intro_image", "path": "board.png", "size": len(image),
             "fingerprint": fingerprint(image), "role": "intro_image"},
            {"id": "intro_audio", "path": "hello.wav", "size": len(voice),
             "fingerprint": fingerprint(voice), "role": "intro_audio"},
        ]
        created = client.post("/api/uploads",
                              json={"key": "web-intro-roundtrip", "manifest": upload})
        assert created.status_code == 201, created.text
        uid = created.json()["id"]
        for fid, data in (("p0", package), ("audio", narration),
                          ("intro_image", image), ("intro_audio", voice)):
            assert put(client, uid, fid, 0, data).status_code == 200
        finished = client.post("/api/uploads/" + uid + "/complete",
                               json={"output_kind": "VIDEO"})
        assert finished.status_code == 202, finished.text
        job = finished.json()["id"]
        for _ in range(300):
            if client.get("/api/jobs/" + job).json()["state"] == "failed":
                break
            time.sleep(0.01)
        saved = client.get("/api/jobs/" + job).json()
        assert saved["state"] == "failed"
        assert len(captured) == 1
        config = captured[0]
        assert isinstance(config, IntroZoomConfig)
        assert (config.focus_x, config.focus_y, config.magnification) == (0.51, 0.26, 3.1)
        assert config.image.read_bytes() == image
        assert config.audio.read_bytes() == voice
