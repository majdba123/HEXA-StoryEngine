# Admin feature verification status

Development branch: `feature/admin-dashboard`, based on `origin/bayer` at `58c3074c6a095c23cee6a6691271ca7241146393`. Production (`bayer`) and integration (`montage`) remain out of scope until explicitly approved.

## Reported prior local tests (Codex session)
Codex reported initial authenticated API/browser tests, a successful expanded Microsoft Edge UI walkthrough, local output deletion, and an earlier web regression pass. The original developer session ended before a conclusive comprehensive core and certified-media report; those assertions are not treated as independent final certification.

## Changes after independent GitHub code review
- Display the ISO-8601 generated-at value on the export inventory table.
- Apply export-root, file-existence and download-lease checks to manifest links; deleted output/manifest links return 404.
- Preserve canonical project identity in the jobs database for failed renders, and retain it on retries. Legacy jobs receive a nullable additive column.
- Replace unmasked browser-prompt password reset with a password-type dialog field.
- Add regression assertions for deletion/download behavior, export dates, role-specific admin markup, and failed job history.
- Add an isolated feature-branch GitHub Actions workflow with no access to production deployment environment or SSH secrets.

## Mandatory outstanding release gates
- A completed, green `HEXA Admin Feature Validation` run for the exact current feature HEAD, including full web, core, FFmpeg, holdout, certification, and visual test suites. Earlier attempts were superseded/cancelled by newer feature commits.
- Windows local `pytest tests/web` and real interactive browser walkthrough with USER and ADMIN accounts.
- One real Final Package ZIP + narration output on the Windows worktree, including both export files and manual download.
- Test deletion with disposable local media only, ensuring bytes reclaimed, historical records preserved, and versions never reused.
- SQLite migration rehearsal using a disposable *copy* of legacy data; no production database modifications.
- Review HTTPS reverse-proxy cookie behavior and first-admin bootstrap configuration before release.
- Separate approval for any merge into `montage`; promotion to `bayer` remains prohibited until integration acceptance.

Do not state PASS or READY until exact current-head test evidence is available. Do not deploy this branch to the VPS.
