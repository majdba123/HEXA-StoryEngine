# Administration architecture decision record

## Starting point

The existing FastAPI application owns `/api/jobs`, resumable `/api/uploads`, downloads, same-origin/host checks, a one-active-job SQLite index, and the `ExportBundleWriter`. The old shared `HEXA_WEB_TOKEN` session was process-local. Upload ownership was one hash of that shared token, so records created before this change cannot be attributed to people.

`LOGIN -> UPLOAD -> VALIDATION -> JOB -> RENDER -> EXPORT -> DOWNLOAD` now uses an SQLite-backed user identity. At every API boundary, the server reloads the session and account state. The browser's role or storage values are never authority.

## Decisions

1. Keep one FastAPI app and one SQLite database, `HEXA_WEB_STORAGE/jobs.sqlite3`.
2. Users have normalized email, Argon2id password hash, role `ADMIN` or `USER`, active/deleted state, timestamps, and a mandatory initial password change for administrator-created accounts.
3. Sessions have random bearer cookies; SQLite stores only SHA-256 digests. Each session has an expiry, revocation state, and a distinct CSRF token digest. Cookies are HttpOnly for the session and SameSite Strict. The CSRF cookie is readable to the same-origin JavaScript; mutations submit it in `X-CSRF-Token`.
4. The legacy shared access token is no longer an authentication path. Missing bootstrap credentials on a new identity database prevent startup. Existing identity databases require an active administrator; bootstrap variables never recreate one.
5. New uploads use the authenticated user ID as owner. New jobs store the user ID. Existing jobs have NULL owner and are visible only to administrators. Existing uploads retain their historical owner token; only administrators may resume them.
6. Admin APIs live under `/api/admin/` and enforce role checks in server middleware and route handlers. HTML `/admin` is protected too.
7. Existing completed exports are indexed from validated manifests. The inventory table retains a logical row after media deletion. Statistics distinguish job rows, version bundles, and MP4 files. Inventory reconciliation is throttled to once per minute.
8. Version deletion first creates a persistent `vN.deleted` tombstone directory. The existing writer's version scanner counts tombstones when reserving a new version. The selected `vN` is renamed to `vN.deleting` and removed. The SQLite row records `DELETING`, `DELETED`, or `DELETE_FAILED`; audit records preserve actor and time. Deletion rejects an active render and active download leases in this process.
9. Production deployment keeps the existing drain/backup pipeline. The online SQLite backup includes identity and inventory tables because they share the jobs database. A deployment requires operator-provided bootstrap secrets before the new application first starts.

## Security boundaries and current limits

- Host and same-origin checks stay in `WebGuard`; they do not authenticate requests.
- No user-supplied path is accepted as a deletion target. The API accepts only an indexed bundle ID, then validates the configured export root and bundle path.
- The web launcher uses one Uvicorn worker. Download leases and deletion locking are process-local; changing worker count requires a cross-process lease before deletion can be certified safe.
- `DELETING` and `DELETE_FAILED` require an operator inspection/recovery path before another deletion attempt. The server fails closed on these states.
- Inventory reconciliation scans the export tree at most once per minute; its first call may be costly on very large legacy stores. A persistent incremental reconciler is a later operational improvement.
- Unique Final Package totals count known completed export identities. Failed legacy jobs without a published bundle do not have a trustworthy package identity and display an unknown package name in history.
