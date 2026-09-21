from __future__ import annotations

import importlib.util
import json
import os
import platform
import shutil
import subprocess
import sys
import traceback
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic
from typing import Any

from app import __version__
from app.config import Settings
from app.models import Stage
from app.shared.errors import HexaError


class BuildReportSession:
    """Collects one generation run and exports a portable diagnostic bundle."""

    SCHEMA_VERSION = 1

    def __init__(
        self,
        *,
        job_id: str,
        settings: Settings,
        package_path: Path,
        audio_path: Path,
        script_path: Path | None = None,
        recovery_root: Path | None = None,
    ) -> None:
        self.job_id = job_id
        self.settings = settings
        self.package_path = package_path.expanduser().resolve()
        self.audio_path = audio_path.expanduser().resolve()
        self.script_path = script_path.expanduser().resolve() if script_path else None
        self.recovery_root = recovery_root or (Path.home() / ".hexa-storyengine" / "recovery")
        self.started_at = datetime.now(timezone.utc)
        self._started_monotonic = monotonic()
        self.finished_at: datetime | None = None
        self.status = "running"
        self.output_path: Path | None = None
        self.stage_events: list[dict[str, Any]] = []
        self.error: dict[str, Any] | None = None
        self.log_path = (self.settings.work_root / self.job_id / "generation.log").resolve()

    def on_progress(self, stage: Stage, value: float, message: str) -> None:
        event = {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "elapsed_seconds": round(monotonic() - self._started_monotonic, 3),
            "stage": stage.value,
            "progress": round(float(value), 4),
            "message": message,
        }
        self.stage_events.append(event)
        self._append_log(
            f"[{round(float(value) * 100):03d}%] {stage.value}: {message}"
        )

    def complete(self, output_path: Path) -> None:
        self.status = "completed"
        self.output_path = output_path.expanduser().resolve()
        self.finished_at = datetime.now(timezone.utc)
        self._append_log(f"DONE: {self.output_path}")

    def fail(self, exc: BaseException) -> None:
        self.status = "failed"
        self.finished_at = datetime.now(timezone.utc)
        details = exc.details if isinstance(exc, HexaError) else {}
        self.error = {
            "type": type(exc).__name__,
            "code": getattr(exc, "code", None),
            "message": str(exc),
            "details": self._sanitize(details),
            "traceback": "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
        }
        self._append_log(f"FAILED: {type(exc).__name__}: {exc}")

    def cancel(self) -> None:
        self.status = "cancelled"
        self.finished_at = datetime.now(timezone.utc)
        self._append_log("CANCELLED")

    def _append_log(self, line: str) -> None:
        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
            with self.log_path.open("a", encoding="utf-8") as handle:
                handle.write(f"{stamp} {line}\n")
        except OSError:
            # Logging must never be allowed to break video generation.
            pass

    def export_zip(self, destination: Path) -> Path:
        destination = destination.expanduser().resolve()
        if destination.suffix.lower() != ".zip":
            destination = destination.with_suffix(".zip")
        destination.parent.mkdir(parents=True, exist_ok=True)

        payload = self._payload()
        recovery_events = self._recovery_events()
        workspace_manifest = self._workspace_manifest()
        markdown = self._markdown(payload, recovery_events, workspace_manifest)

        with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("report.json", json.dumps(payload, ensure_ascii=False, indent=2))
            archive.writestr("report.md", markdown)
            archive.writestr(
                "recovery-events.json",
                json.dumps(recovery_events, ensure_ascii=False, indent=2),
            )
            archive.writestr(
                "workspace-manifest.json",
                json.dumps(workspace_manifest, ensure_ascii=False, indent=2),
            )
        return destination

    def _payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.SCHEMA_VERSION,
            "job_id": self.job_id,
            "status": self.status,
            "started_at_utc": self.started_at.isoformat(),
            "finished_at_utc": self.finished_at.isoformat() if self.finished_at else None,
            "duration_seconds": self._duration_seconds(),
            "build": self._build_info(),
            "environment": self._environment_info(),
            "inputs": {
                "final_package": self._path_metadata(self.package_path),
                "audio": self._path_metadata(self.audio_path),
                "script": self._path_metadata(self.script_path) if self.script_path else None,
            },
            "output": self._path_metadata(self.output_path) if self.output_path else None,
            "settings": {
                "work_root": self._display_path(self.settings.work_root),
                "output_root": self._display_path(self.settings.output_root),
                "ffmpeg_bin": self.settings.ffmpeg_bin,
                "ffprobe_bin": self.settings.ffprobe_bin,
                "whisper_model": self.settings.whisper_model,
                "allow_scene_fallback": self.settings.allow_scene_fallback,
            },
            "stage_events": self.stage_events,
            "log_file": self._path_metadata(self.log_path),
            "last_stage": self.stage_events[-1]["stage"] if self.stage_events else None,
            "error": self.error,
        }

    def _build_info(self) -> dict[str, Any]:
        repo_root = Path(__file__).resolve().parents[2]
        return {
            "app_version": __version__,
            "git_commit": self._run_text(["git", "rev-parse", "HEAD"], cwd=repo_root),
            "git_branch": self._run_text(["git", "branch", "--show-current"], cwd=repo_root),
        }

    def _environment_info(self) -> dict[str, Any]:
        return {
            "platform": platform.platform(),
            "python": sys.version.replace("\n", " "),
            "python_executable": self._display_path(Path(sys.executable)),
            "ffmpeg": self._binary_version(self.settings.ffmpeg_bin),
            "ffprobe": self._binary_version(self.settings.ffprobe_bin),
            "nvidia_gpu": self._nvidia_info(),
            "modules": {
                "PySide6": self._module_available("PySide6"),
                "faster_whisper": self._module_available("faster_whisper"),
                "torch": self._module_available("torch"),
                "transformers": self._module_available("transformers"),
            },
            "cpu_count": os.cpu_count(),
        }

    def _recovery_events(self) -> list[dict[str, Any]]:
        history_path = self.recovery_root / "recovery-history.jsonl"
        if not history_path.is_file():
            return []
        events: list[dict[str, Any]] = []
        try:
            with history_path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        payload = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if payload.get("job_id") == self.job_id:
                        events.append(self._sanitize(payload))
        except OSError:
            return []
        return events

    def _workspace_manifest(self) -> dict[str, Any]:
        root = (self.settings.work_root / self.job_id).resolve()
        if not root.exists():
            return {"root": self._display_path(root), "files": [], "truncated": False}
        files: list[dict[str, Any]] = []
        truncated = False
        for index, path in enumerate(sorted(p for p in root.rglob("*") if p.is_file())):
            if index >= 5000:
                truncated = True
                break
            try:
                size = path.stat().st_size
            except OSError:
                size = None
            files.append({"path": str(path.relative_to(root)), "size_bytes": size})
        return {"root": self._display_path(root), "files": files, "truncated": truncated}

    def _path_metadata(self, path: Path | None) -> dict[str, Any] | None:
        if path is None:
            return None
        path = path.expanduser().resolve()
        result: dict[str, Any] = {
            "name": path.name,
            "path": self._display_path(path),
            "exists": path.exists(),
            "kind": "directory" if path.is_dir() else "file",
        }
        try:
            if path.is_file():
                result["size_bytes"] = path.stat().st_size
            elif path.is_dir():
                count = 0
                total = 0
                for child in path.rglob("*"):
                    if child.is_file():
                        count += 1
                        try:
                            total += child.stat().st_size
                        except OSError:
                            pass
                result["file_count"] = count
                result["size_bytes"] = total
        except OSError:
            pass
        return result

    def _binary_version(self, command: str) -> dict[str, Any]:
        executable = shutil.which(command) if not Path(command).is_file() else str(Path(command).resolve())
        if not executable:
            return {"available": False, "command": command}
        output = self._run_text([executable, "-version"])
        first_line = output.splitlines()[0] if output else None
        return {"available": True, "path": self._display_path(Path(executable)), "version": first_line}

    def _nvidia_info(self) -> str | None:
        executable = shutil.which("nvidia-smi")
        if not executable:
            return None
        return self._run_text([
            executable,
            "--query-gpu=name,driver_version,memory.total",
            "--format=csv,noheader",
        ]) or None

    @staticmethod
    def _module_available(name: str) -> bool:
        return importlib.util.find_spec(name) is not None

    @staticmethod
    def _run_text(command: list[str], cwd: Path | None = None) -> str:
        try:
            result = subprocess.run(
                command,
                cwd=str(cwd) if cwd else None,
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (OSError, subprocess.SubprocessError):
            return ""
        return (result.stdout or result.stderr or "").strip()

    def _display_path(self, path: Path) -> str:
        value = str(path.expanduser().resolve())
        home = str(Path.home().resolve())
        if value == home:
            return "~"
        if value.startswith(home + os.sep):
            return "~" + value[len(home):]
        return value

    def _sanitize(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {str(key): self._sanitize(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self._sanitize(item) for item in value]
        if isinstance(value, tuple):
            return [self._sanitize(item) for item in value]
        if isinstance(value, Path):
            return self._display_path(value)
        if isinstance(value, str):
            home = str(Path.home().resolve())
            return value.replace(home, "~")
        return value

    def _duration_seconds(self) -> float:
        end = self.finished_at or datetime.now(timezone.utc)
        return round((end - self.started_at).total_seconds(), 3)

    @staticmethod
    def _markdown(
        payload: dict[str, Any],
        recovery_events: list[dict[str, Any]],
        workspace_manifest: dict[str, Any],
    ) -> str:
        build = payload["build"]
        env = payload["environment"]
        lines = [
            "# HEXA Diagnostic Report",
            "",
            f"- Job: `{payload['job_id']}`",
            f"- Status: **{payload['status']}**",
            f"- App version: `{build.get('app_version')}`",
            f"- Commit: `{build.get('git_commit') or 'unknown'}`",
            f"- Branch: `{build.get('git_branch') or 'unknown'}`",
            f"- Duration: `{payload['duration_seconds']}s`",
            f"- Platform: `{env.get('platform')}`",
            "",
            "## Inputs",
            "",
            f"- Final Package: `{payload['inputs']['final_package']['name']}`",
            f"- Audio: `{payload['inputs']['audio']['name']}`",
            "",
            "## Pipeline Steps",
            "",
        ]
        for event in payload["stage_events"]:
            percent = round(event["progress"] * 100)
            lines.append(
                f"- `{event['elapsed_seconds']:>8.3f}s` [{percent:>3}%] "
                f"**{event['stage']}** — {event['message']}"
            )
        if payload.get("error"):
            error = payload["error"]
            lines.extend([
                "",
                "## Failure",
                "",
                f"- Type: `{error.get('type')}`",
                f"- Code: `{error.get('code')}`",
                f"- Message: {error.get('message')}",
                "",
                "```text",
                error.get("traceback") or "",
                "```",
            ])
        lines.extend([
            "",
            "## Recovery",
            "",
            f"Recovery events for this job: **{len(recovery_events)}**",
            "",
            "## Workspace",
            "",
            f"Tracked files: **{len(workspace_manifest.get('files', []))}**",
            f"Truncated: **{workspace_manifest.get('truncated', False)}**",
            "",
            "> Raw Final Package media and audio are not copied into this diagnostic ZIP.",
            "",
        ])
        return "\n".join(lines)
