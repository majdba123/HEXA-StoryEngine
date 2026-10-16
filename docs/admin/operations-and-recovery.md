# Operations and recovery

## Administrator recovery

If no administrator can log in, stop the service and take a verified SQLite online backup. Inspect `users` and `identity_audit` in a restricted offline environment. If there is genuinely no active administrator, run the explicit offline utility with a distinct recovery email:

```bash
python -m app.web.restore_admin --db /var/lib/hexa-storyengine/web/jobs.sqlite3 --email recovery@example.com --backup-confirmed
```

The utility prompts without echoing the password, refuses to elevate an existing user, and writes an audit event. Restart the service and log in. Do not set a plaintext password in SQLite, re-enable a shared web token, or rely on persistent bootstrap variables to recreate an account.

## Export deletion

The admin API records `DELETING` before moving the selected version. It creates `vN.deleted` so the writer will never reuse the version number. If a delete fails, `DELETE_FAILED` is visible; inspect `vN`, `vN.deleting`, and `vN.deleted` under the validated package directory with the service stopped. Preserve the SQLite and filesystem state before manual correction. Do not delete the tombstone directory.

The application uses one web worker. Keep this constraint while relying on process-local download leases. Do not run manual filesystem deletions concurrently with rendering or downloads.

## Audit and retention

Authentication and account changes are recorded in `identity_audit`; no plaintext passwords or session cookies are stored there. Existing input retention removes old uploads, not completed exports. Administrative deletion removes media while retaining the job and inventory rows. Back up the SQLite database before any maintenance of identity, audit, or inventory tables.

Disabling a user revokes their sessions immediately. A render already admitted continues to completion so that the media and job record are not corrupted; the disabled account cannot poll it, start another job, or download it. An administrator can inspect its result.
