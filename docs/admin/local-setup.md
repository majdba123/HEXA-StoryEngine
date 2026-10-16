# Local Windows montage trial

Run only from the local `montage` checkout in VS Code. No MySQL, Docker, or separate database server is required. SQLite is created automatically.

For a **clean local test**, stop the current web server and run:

```powershell
git pull --ff-only origin montage
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\start_local_montage.ps1 -Reset
```

The script refuses to run from a different branch. It moves the previous `.hexa/montage-local` folder (SQLite, uploads, outputs, exports, work files) into an archive under `.hexa/local-archives`, **without deleting or copying the media**, and starts with fresh paths. The archive is intentionally retained for manual recovery. The `-Reset` switch is explicit because existing local state must not be overwritten accidentally.

**Local-only demonstration accounts**, created once in the fresh SQLite database:

| Role | Email | Initial password |
|---|---|---|
| ADMIN | `majd@gmail.com` | `password2026!` |
| USER | `majd1@gmail.com` | `password2026!` |

The USER must change their temporary password on first login. The ADMIN can change passwords from the dashboard. These demonstration passwords meet the length validator but are publicly known and **must never be used in production**. The originally requested `password` is deliberately rejected by the application's 12-character minimum.

Open `http://127.0.0.1:8788/login` after the server starts. Keep the terminal open while testing. Use `Ctrl+C` to stop. For a normal subsequent start preserving the current database, omit `-Reset`. Never run this script on the VPS.

Production is configured through environment secrets, not the local PowerShell script: on a fresh production identity DB, the bootstrap creates the admin and optional user with distinct, strong secrets and does not reset either one on restart.
