# Production activation handoff

No VPS change is performed by this branch. Before any promotion to `bayer`, the operator must:

1. Review local login, user actions, upload resume, real rendering, export inventory, and one-version deletion.
2. Verify a bounded, integrity-checked production SQLite backup; confirm no active job or recent resumable upload. Do not duplicate rendered video files on the VPS for backup: exported media is downloaded and retained by the operator outside the VPS. Verify existing export directories and free disk space without copying the media.
3. Supply `HEXA_ADMIN_EMAIL=majd@gmail.com` and a **unique strong** `HEXA_ADMIN_BOOTSTRAP_PASSWORD` through the protected service environment. For an additional initial USER on a **new identity database only**, also supply `HEXA_INITIAL_USER_EMAIL=majd1@gmail.com` and a different strong `HEXA_INITIAL_USER_PASSWORD`. Both initial accounts are created atomically once and never overwritten. Never deploy known local demonstration passwords such as `password` or `password2026!`. Keep the bootstrap password outside Git, logs, shell history, and chat. Set `HEXA_WEB_ALLOWED_HOSTS=studio.hexaterminal.com`, keep HTTPS termination and the existing storage paths, and verify the proxy delivers the HTTPS scheme so session and CSRF cookies carry `Secure`.
4. Remove `HEXA_WEB_TOKEN` from the service environment after activation. It is ignored by this code, but leaving an obsolete secret increases confusion.
5. Review the migration on a copy of the real jobs database, including legacy jobs and uploads, and test the admin-only legacy boundary.
6. Approve promotion to `bayer` separately. Use the established CI/CD pipeline and its deployment gate; inspect exact SHA, readiness, login, and real output after deployment.

If activation fails, do not restore a stale SQLite backup blindly. First preserve the failed state and compare its job and identity records with the backup. The old token interface must not be put back online without a deliberate security decision.
