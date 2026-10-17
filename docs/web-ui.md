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

Remaining production work: export-bundle retention policy, measured CPU/RAM/disk limits on the target machine, and a reviewed deployment and rollback procedure. Terminal web jobs write a diagnostic ZIP to job storage, so the report remains downloadable after a server restart while the retained job directory exists.

The web UI is integrated in `montage`; `HEXA.bat` remains the desktop fallback.

## Resumable upload candidate (`montage`)

The browser now uses `POST /api/uploads` with `{key,manifest}` before any bytes move. The manifest declares `mode` (`zip` or `folder`) and files with `id`, safe relative `path`, `size`, `role` (`package` or `audio`), and `fingerprint`. The fingerprint is SHA-256 of concatenated lowercase SHA-256 hex digests of consecutive configured slices; it is intentionally **not** the file's ordinary SHA-256. This scheme allows bounded browser memory. Each `PUT /api/uploads/{id}/files/{file_id}/chunks/{index}` carries raw bytes and `X-Chunk-SHA256`. Only the next negotiated slice is accepted; identical retries return the committed offset. `GET /api/uploads/config` returns the legacy V1 chunk size (256 KiB by default; 512 KiB and 1 MiB are permitted through `HEXA_WEB_CHUNK_BYTES`) plus V2 capability and a 4 MiB V2 recommendation when `HEXA_WEB_V2_ENABLED=1` (default `0`). Turning the flag off stops new V2 sessions while preserving existing V2 resumes. A new browser session explicitly records `protocol: 2` and the chosen size in its manifest; V1 sessions retain their stored size and fingerprint semantics. The V2 browser consumes the committed offset returned by each chunk PUT, requesting full status only for recovery. `GET /api/uploads/{id}` returns authoritative offsets, manifest, state, and job ID. `POST /api/uploads/{id}/complete` verifies all slices again, checks ZIP/audio/Final Package, and atomically associates one admitted job. Repeating completion returns that job. `DELETE /api/uploads/{id}` explicitly discards only an unadmitted upload. Private routes use the existing web guard.

Upload metadata lives in `jobs.sqlite3` (`uploads`, `upload_files`, `upload_chunks`, and `upload_create_events`). Raw chunks live under `<HEXA_WEB_UPLOAD_ROOT>/<opaque-id>/<file-id>` outside the web root. When `HEXA_WEB_STORAGE` is explicitly configured, the upload root defaults to its `uploads` child; otherwise it defaults to `~/.hexa/uploads` outside the checkout. Set both roots explicitly on a VPS and migrate any existing default upload data before changing them. A write is flushed and fsynced before the SQLite offset moves. If the server stops after writing bytes but before updating SQLite, the next chunk truncates unacknowledged bytes to the stored offset. The browser keeps the upload ID in localStorage and caches files up to 100 MiB in IndexedDB when the browser permits it. A cache failure leaves server offsets intact; the user selects the same files again and the browser checks the fingerprint before resuming. Firefox file permissions are not presumed to survive refresh. Browser close pauses transfer but never cancels admitted generation.

`HEXA_WEB_MAX_UPLOAD_BYTES` limits each file and the combined manifest to twice that limit. Session count is capped at 100, active incomplete sessions reserve at most `HEXA_WEB_TOTAL_UPLOAD_BYTES` (default: twice `HEXA_WEB_MAX_UPLOAD_BYTES`) in aggregate, and creation is limited to 10 sessions per owner per minute. Free disk space is checked at creation. With `HEXA_WEB_RETENTION_DAYS`, startup removes expired incomplete or failed uploads and inputs of terminal jobs; active jobs remain untouched. A failed render with retained inputs can be retried explicitly through `POST /api/jobs/{id}/retry`; the one-active-job SQLite index still applies. A server crash during rendering marks the orphaned job failed rather than claiming exact mid-render resumption. Future deployment automation should check `/ready` and refuse a deploy while `active_job` is non-null.

The original multipart `POST /api/jobs` remains for compatibility. The upload protocol is integrated into `montage` as a development candidate and remains disabled by default. The isolated Firefox refresh test and simulated slow-link benchmarks have passed; real-network, full-corpus, and encoded-output certification remain necessary before promotion to `bayer`. `bayer` remains untouched.

### Upload API responses and recovery

| Operation | Success | Recovery or error |
| --- | --- | --- |
| `GET /api/uploads/config` | 200 with selected chunk size and file limit | 401 if authentication is required |
| `POST /api/uploads` | 201 with opaque upload ID and offsets; same key and manifest returns the same ID | 409 for a conflicting key, 413 for a manifest over 1 MiB, 429 for creation rate limit, 507 for low disk space |
| `GET /api/uploads/{id}` | 200 with state, offsets, verified whole-file SHA-256 hashes when available, timestamps, and associated job ID | 404 for unknown or inaccessible ID |
| `PUT /api/uploads/{id}/files/{file_id}/chunks/{index}` | 200 only after fsync and SQLite commit; identical retry returns the same offset | 409 for a conflicting or out-of-order chunk, 413 for excess bytes, 422 for a bad hash or length, 507 for disk full |
| `POST /api/uploads/{id}/complete` | 202 with the admitted job ID; repeated calls return the same ID | 409 while incomplete, already validating, or another render is active; 422 for invalid input or package; 507 for disk full |
| `POST /api/uploads/{id}/retry` | 200 resets a failed validation while retaining uploaded chunks | 409 if the upload is not retryable |
| `DELETE /api/uploads/{id}` | 200 discards an unadmitted upload after the UI confirmation | 409 once a job is admitted |
| `POST /api/jobs/{id}/retry` | 202 creates a new job from retained inputs of a failed job | 409 if inputs are missing or another job is active |

The upload state machine is `uploading -> validating -> queued` or `failed`; `queued` links to the existing independent job state machine (`queued -> running -> completed/failed/canceled`). The client never treats page unload as cancellation. After process failure, a live worker is not assumed stopped; orphaned render jobs are marked failed by the existing owner check, and orphaned validation claims are returned to `uploading` while their committed chunks remain intact. Multi-worker deployments must share the configured storage and SQLite file. Deployment automation should check for an active job and wait for an idle window before stopping a service.
