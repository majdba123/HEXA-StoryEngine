# HEXA Web UI

The web server accepts a Unified Final Package 2.0 ZIP or a browser selected directory and narration audio. It validates both uploads, stores them in a server owned job directory, and calls the unchanged `StoryEnginePipeline.generate_bundle()` with its progress and cancellation callbacks. Browser directory files are packed into a validated ZIP in that job directory. The canonical export bundle remains under the configured `HEXA_EXPORT_ROOT` (or `export_root` in `hexa.settings.json`). Browser downloads use the resulting MP4 files and manifest.

## Windows local start

Use the project's existing Python 3.11 environment. In this isolated worktree, set `HEXA_WEB_PYTHON` to the existing environment's `python.exe` if `.venv` is elsewhere. Install the project in that environment once with `python -m pip install -e ".[dev]"` if its web dependencies are missing. Ensure `ffmpeg` and `ffprobe` are on `PATH` and the production export root is configured. Double click `HEXA-WEB.bat`; it binds to `127.0.0.1:8787` and opens the browser when ready. Ctrl+C in the launcher stops the server after active worker threads finish. `HEXA.bat` remains available for the desktop UI.

## Configuration

`HEXA_WEB_PORT` defaults to 8787. `HEXA_WEB_STORAGE` defaults to `.hexa/web` and owns uploaded files and SQLite job metadata. `HEXA_WEB_MAX_UPLOAD_BYTES` defaults to 2 GiB per file. `HEXA_EXPORT_ROOT`, `HEXA_WORK_ROOT`, `HEXA_FFMPEG`, and `HEXA_FFPROBE` retain their engine meanings. Logs are written by `BuildReportSession` under the engine work root. Only one job is admitted at a time, including while cancellation is in progress. A restarted server marks orphaned jobs failed.

Refreshing or reopening the page reconnects to the server's active job and restores its progress and log. The browser remembers the last job to restore completed results. The server rejects a second job while one is queued, running, or cancelling. Upload copying, ZIP checks, audio probing, package loading, and export root checks run outside the ASGI event loop so status and health requests remain responsive during validation.

## Server preparation

The same ASGI application can be launched with `uvicorn app.web.server:app --host 127.0.0.1 --port 8787 --workers 1`. The current interface has no authentication. Before any public or VPS deployment, put it behind authenticated private access and a reverse proxy, configure server storage and retention, and verify resource limits. Never expose `app.api` as the public upload interface. Deployment automation and production rollout are separate work.

Production blockers are: authentication and access control; retention and precise cleanup for uploads, diagnostics, and export bundles; measured CPU, RAM, disk, and worker limits for the target machine; and a reviewed deployment and rollback procedure. The web module does not implement those policies. Diagnostic ZIP downloads currently require the server process that generated the job.

For integration, compare this branch against the recorded `origin/montage` baseline, then rebase or merge only after the engine developer has finished and the user authorizes integration. Resolve any conflicts in shared CI or docs without replacing newer engine files, rerun web tests and existing certification gates, and retain `HEXA.bat` for rollback.
