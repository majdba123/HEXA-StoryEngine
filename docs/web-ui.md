# HEXA Web UI

The web server accepts a Unified Final Package 2.0 ZIP or a browser selected directory and narration audio. It validates both uploads, stores them in a server owned job directory, and calls the unchanged `StoryEnginePipeline.generate_bundle()` with its progress and cancellation callbacks. Browser directory files are packed into a validated ZIP in that job directory. The canonical export bundle remains under the configured `HEXA_EXPORT_ROOT` (or `export_root` in `hexa.settings.json`). Browser downloads use the resulting MP4 files and manifest.

## Windows local start

Use the project's existing Python 3.11 environment. In this isolated worktree, set `HEXA_WEB_PYTHON` to the existing environment's `python.exe` if `.venv` is elsewhere. Install the project in that environment once with `python -m pip install -e ".[dev]"` if its web dependencies are missing. Ensure `ffmpeg` and `ffprobe` are on `PATH` and the production export root is configured. Double click `HEXA-WEB.bat`; it binds to `127.0.0.1:8787` and opens the browser when ready. Ctrl+C in the launcher stops the server after active worker threads finish. `HEXA.bat` remains available for the desktop UI.

## Configuration

`HEXA_WEB_PORT` defaults to 8787. `HEXA_WEB_STORAGE` defaults to `.hexa/web` and owns uploaded files and SQLite job metadata. `HEXA_WEB_MAX_UPLOAD_BYTES` defaults to 2 GiB per file. `HEXA_EXPORT_ROOT`, `HEXA_WORK_ROOT`, `HEXA_FFMPEG`, and `HEXA_FFPROBE` retain their engine meanings. Logs are written by `BuildReportSession` under the engine work root. Only one job is admitted at a time, including while cancellation is in progress. A restarted server marks orphaned jobs failed.

Refreshing or reopening the page reconnects to the server's active job and restores its progress and log. The browser remembers the last job to restore completed results. The server rejects a second job while one is queued, running, or cancelling. Upload copying, ZIP checks, audio probing, package loading, and export root checks run outside the ASGI event loop so status and health requests remain responsive during validation.

## Security guards (all modes)

* **Same-origin writes.** Every POST/PUT/PATCH/DELETE with a foreign `Origin` or
  `Sec-Fetch-Site: cross-site` is refused (403), so another web page cannot start or cancel
  a render on the local server.
* **Allowed hosts.** Requests whose `Host` is not a loopback name (or a name listed in
  `HEXA_WEB_ALLOWED_HOSTS`) are refused (421), which blocks DNS-rebinding against
  `127.0.0.1:8787`.
* **Request size.** A request whose `Content-Length` exceeds twice
  `HEXA_WEB_MAX_UPLOAD_BYTES` plus 1 MiB is refused (413) before the upload is read.
* **Access token.** With `HEXA_WEB_TOKEN` set, every `/api/` route except `/api/session`
  requires either `Authorization: Bearer <token>` or the HttpOnly, SameSite=Strict session
  cookie issued by `POST /api/session {"token": ...}`; the page asks for the token once.
  The launcher refuses to listen on a non-loopback `HEXA_WEB_HOST` without a token.
* **Headers.** `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`,
  `Referrer-Policy: no-referrer` and a same-origin Content-Security-Policy on every response.
* **Security log.** Refusals, logins and job admissions/cancellations are appended to
  `<HEXA_WEB_STORAGE>/security.log`.
* **Readiness.** `GET /ready` returns 503 with concrete problems (export root, FFmpeg,
  FFprobe, storage) and the active job id; `GET /health` is liveness only.
* **Retention.** `HEXA_WEB_RETENTION_DAYS` removes uploaded inputs of finished jobs older
  than N days at startup. Export bundles under the export root are never deleted.

## Server preparation

The same ASGI application can be launched with `uvicorn app.web.server:app --host 127.0.0.1 --port 8787 --workers 1`. Before any public or VPS deployment set `HEXA_WEB_TOKEN`, `HEXA_WEB_ALLOWED_HOSTS` and `HEXA_WEB_RETENTION_DAYS`, put it behind TLS on a reverse proxy, and verify resource limits (see `docs/qa/VPS-DEPLOYMENT-READINESS.md`). Never expose `app.api` as the public upload interface. Deployment automation and production rollout are separate work.

Remaining production work: export-bundle retention policy, measured CPU/RAM/disk limits on the target machine, and a reviewed deployment and rollback procedure. Diagnostic ZIP downloads still require the server process that generated the job.

The web UI is integrated in `montage`; `HEXA.bat` remains the desktop fallback.
