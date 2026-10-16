# Local Windows montage trial

Run only from the local `montage` checkout in VS Code. No MySQL, Docker, or separate database server is required. SQLite is created automatically.

For a **clean local test**, stop the current web server and run:

```powershell
git pull --ff-only origin montage
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\start_local_montage.ps1 -Reset
```

The script refuses to run from a different branch. With `-Reset`, it **permanently deletes only** `.hexa/montage-local` (its SQLite database, local test uploads, work files, and local test exports) before creating a fresh database. **No archive or backup is created.** It rejects linked directories/files and a running local server on port 8788. This is intentionally destructive, so do not pass `-Reset` after you have real local work you want to keep. The user requested a clean start without archiving the previous local test database; pre-existing `.hexa/local-archives` from earlier runs are not touched.

**Local-only demonstration accounts**, created once in the fresh SQLite database:

| Role | Email | Initial password |
|---|---|---|
| ADMIN | `majd@gmail.com` | `password2026!` |
| USER | `majd1@gmail.com` | `password2026!` |

The USER must change their temporary password on first login. The ADMIN can change passwords from the dashboard. These demonstration passwords meet the length validator but are publicly known and **must never be used in production**. The originally requested `password` is deliberately rejected by the application's 12-character minimum.

Open `http://127.0.0.1:8788/login` after the server starts. Keep the terminal open while testing. Use `Ctrl+C` to stop. For a normal subsequent start preserving the current database, omit `-Reset`. Never run this script on the VPS.

Production is configured through environment secrets, not the local PowerShell script: on a fresh production identity DB, the bootstrap creates the admin and optional user with distinct, strong secrets and does not reset either one on restart.
