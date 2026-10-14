# HEXA Web UI

The web server accepts a Unified Final Package 2.0 ZIP and narration audio. It validates both uploads, stores them in a server owned job directory, and calls the unchanged `StoryEnginePipeline.generate_bundle()` with its progress and cancellation callbacks. The canonical export bundle remains under the configured `HEXA_EXPORT_ROOT` (or `export_root` in `hexa.settings.json`). Browser downloads use the resulting MP4 files and manifest.

## Windows local start

Use the project's existing Python 3.11 environment. In this isolated worktree, set `HEXA_WEB_PYTHON` to the existing environment's `python.exe` if `.venv` is elsewhere. Install the project in that environment once with `python -m pip install -e ".[dev]"` if its web dependencies are missing. Ensure `ffmpeg` and `ffprobe` are on `PATH` and the production export root is configured. Double click `HEXA-WEB.bat`; it binds to `127.0.0.1:8787` and opens the browser when ready. Ctrl+C in the launcher stops the server after active worker threads finish. `HEXA.bat` remains available for the desktop UI.

## Configuration

`HEXA_WEB_PORT` defaults to 8787. `HEXA_WEB_STORAGE` defaults to `.hexa/web` and owns uploaded files and SQLite job metadata. `HEXA_WEB_MAX_UPLOAD_BYTES` defaults to 2 GiB per file. `HEXA_EXPORT_ROOT`, `HEXA_WORK_ROOT`, `HEXA_FFMPEG`, and `HEXA_FFPROBE` retain their engine meanings. Logs are written by `BuildReportSession` under the engine work root. Only one job is admitted at a time, including while cancellation is in progress. A restarted server marks orphaned jobs failed.

## Server preparation

The same ASGI application can be launched with `uvicorn app.web.server:app --host 127.0.0.1 --port 8787 --workers 1`. The current interface has no authentication. Before any public or VPS deployment, put it behind authenticated private access and a reverse proxy, configure server storage and retention, and verify resource limits. Never expose `app.api` as the public upload interface. Deployment automation and production rollout are separate work.

For integration, compare this branch against the recorded `origin/montage` baseline, then rebase or merge only after the engine developer has finished and the user authorizes integration. Resolve any conflicts in shared CI or docs without replacing newer engine files, rerun web tests and existing certification gates, and retain `HEXA.bat` for rollback.
