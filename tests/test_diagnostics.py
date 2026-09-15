from __future__ import annotations

import json
import zipfile
from pathlib import Path

from app.config import Settings
from app.diagnostics import BuildReportSession
from app.models import Stage
from app.shared.errors import StageFailedError


def test_diagnostic_report_captures_pipeline_failure(tmp_path: Path) -> None:
    package = tmp_path / "package"
    package.mkdir()
    (package / "scene.png").write_bytes(b"fake-scene")
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"fake-audio")

    settings = Settings(
        work_root=tmp_path / "work",
        output_root=tmp_path / "outputs",
        ffmpeg_bin="ffmpeg",
        ffprobe_bin="ffprobe",
        whisper_model="small",
        engine_host="127.0.0.1",
        engine_port=8765,
        allow_scene_fallback=False,
    )
    job_id = "diagnostic-test-job"
    workspace = settings.work_root / job_id
    workspace.mkdir(parents=True)
    (workspace / "render-plan.json").write_text("{}", encoding="utf-8")

    recovery_root = tmp_path / "recovery"
    recovery_root.mkdir()
    recovery_event = {
        "issue_code": "LOW_SCREEN_OCCUPANCY",
        "job_id": job_id,
        "package_id": "pkg",
        "handler": "reflow_composition",
        "handler_version": 1,
        "attempt": 1,
        "success": False,
        "details": {"remaining_issue_count": 1},
        "occurred_at": "2026-09-15T00:00:00+00:00",
    }
    (recovery_root / "recovery-history.jsonl").write_text(
        json.dumps(recovery_event) + "\n",
        encoding="utf-8",
    )

    report = BuildReportSession(
        job_id=job_id,
        settings=settings,
        package_path=package,
        audio_path=audio,
        recovery_root=recovery_root,
    )
    report.on_progress(Stage.input, 0.04, "Reading Final Package")
    report.on_progress(Stage.story, 0.43, "Building visual story")
    report.fail(StageFailedError("story failed", details={"reason": "test"}))

    destination = report.export_zip(tmp_path / "diagnostic.zip")
    assert destination.exists()

    with zipfile.ZipFile(destination) as archive:
        assert set(archive.namelist()) == {
            "report.json",
            "report.md",
            "recovery-events.json",
            "workspace-manifest.json",
        }
        payload = json.loads(archive.read("report.json"))
        recovery = json.loads(archive.read("recovery-events.json"))
        workspace_payload = json.loads(archive.read("workspace-manifest.json"))

    assert payload["status"] == "failed"
    assert payload["last_stage"] == "story"
    assert payload["error"]["code"] == "STAGE_FAILED"
    assert payload["error"]["details"]["reason"] == "test"
    assert recovery[0]["issue_code"] == "LOW_SCREEN_OCCUPANCY"
    assert workspace_payload["files"][0]["path"] == "render-plan.json"
