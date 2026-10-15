# HEXA Web — VPS deployment readiness (not deployed)

Target: ~4 vCPU, 8 GB RAM, no GPU, other services already running. Nothing in this
assignment touches the live VPS. This checklist states what exists, what was measured and
what must still be done before a public release.

## Implemented in the application

| Area | State | Where |
|---|---|---|
| Loopback-only by default | `HEXA_WEB_HOST=127.0.0.1`; non-loopback bind refused without a token | `app/web/__main__.py` |
| Authentication | `HEXA_WEB_TOKEN`: Bearer header or HttpOnly SameSite=Strict session cookie | `app/web/security.py` |
| CSRF | Unsafe methods with a foreign `Origin` or `Sec-Fetch-Site: cross-site` refused | `WebGuard.refusal` |
| DNS rebinding | `Host` must be loopback or listed in `HEXA_WEB_ALLOWED_HOSTS` | `WebGuard.refusal` |
| Upload size | `HEXA_WEB_MAX_UPLOAD_BYTES` per file; request `Content-Length` cap before parsing | server + guard |
| ZIP bomb / traversal | entry count, unpacked size, ratio, symlink, absolute/parent paths, CRC | `app/web/validation.py` |
| Folder upload traversal | per-path validation before packing | `save_folder` |
| Download authorization | job outputs only, path must stay in the bundle; token-protected when enabled | `download` route |
| Single job admission | SQLite unique partial index (atomic across processes) | `app/web/jobs.py` |
| Restart recovery | orphaned jobs marked failed at startup; active job restored in the page | `Jobs.__init__`, `app.js` |
| Retention | `HEXA_WEB_RETENTION_DAYS` purges uploaded inputs of finished jobs; exports never deleted | `Jobs.purge_uploads` |
| Security logging | refusals, logins, admissions, cancellations → `<storage>/security.log` | guard |
| Health / readiness | `/health` liveness; `/ready` 503 with export-root/FFmpeg/storage problems | server |
| Security headers | X-Frame-Options, nosniff, Referrer-Policy, CSP | middleware |

## Measured on the development machine (i7-7500U, 2 cores / 4 threads, 8 GB)

See `docs/qa/VNEXT-EXECUTION-STATE.md` for the measured web end-to-end run (wall time,
peak RSS, output sizes). The engine is CPU-only; no CUDA path is assumed.

## Still required before a public release (blockers)

1. TLS-terminating reverse proxy (nginx/Caddy) in front of `127.0.0.1:8787`; set
   `HEXA_WEB_ALLOWED_HOSTS` to the public name; keep `HEXA_WEB_HOST=127.0.0.1`.
2. Secret management for `HEXA_WEB_TOKEN` (not in Git; rotate on staff change).
3. A service unit with resource limits, e.g. systemd `CPUQuota=300%`, `MemoryMax=6G`,
   `Nice=10`, restart on failure, `WorkingDirectory` on the release directory.
4. Export-bundle retention policy for `HEXA_EXPORT_ROOT` (deliberately not automatic).
5. Disk quota/monitoring for `HEXA_WORK_ROOT`, `HEXA_WEB_STORAGE` and the export root.
6. Release procedure: install a tagged commit into a new directory, run `/ready`, switch the
   service, keep the previous directory for rollback; CI must be green on that exact SHA.
7. Model/cache warm-up on the VPS (speech alignment model download) before opening access.
8. Diagnostics ZIP after a restart is unavailable (documented limitation).

## Rollback

Desktop `HEXA.bat` remains the fallback on Windows. On the server, rollback is switching
the service back to the previous release directory; job storage and exports are outside
the release directory.
