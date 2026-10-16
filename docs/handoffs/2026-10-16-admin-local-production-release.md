# HEXA StoryEngine — Admin / Local / Production Release Handoff
**Checkpoint date:** 2026-10-16  
**Scope:** This conversation's complete operational handoff, not a rewrite of historic StoryEngine architecture.  
**Repo:** majdba123/HEXA-StoryEngine  
**Canonical history:** \`HEXA_PROJECT_CONTINUITY_SOURCE.md\` remains authoritative for pre-existing architecture; **this is the latest checkpoint for the Admin/production rollout**.  
**Safety:** Never put production passwords, private keys, tokens, or complete /etc/hexa-storyengine/hexa.env contents in commits, prompts, chat, or logs.

## 0) Critical status — latest GitHub snapshot, do not assume VPS deployed
- Immediately **before this documentation-only handoff commit**, GitHub branches \`montage\` and \`bayer\` were **identical** at \`638be6b69e7357d046cad0cb64023ae26afb92bd\`. The remote \`feature/admin-dashboard\` branch had already been deleted.
- This happened **after** previous advice to refrain from merging. **Do NOT merge or push again just because older messages say it remains to do.** A new handoff-only commit on \`montage\` may make \`montage\` one or two docs-only commits ahead of \`bayer\`, which is NOT missing application functionality.
- \`montage\` full admin validation: GitHub Actions \`38866168216\`, **SUCCESS**, on code SHA \`638be6b\`. Prior success \`38865209672\` on \`e745f40d\`.
- Two production \`HEXA CI/CD (Bayer)\` runs existed during the last lookup: \`38868875613\` for SHA \`6b7d2ee...\` **in progress**, and \`38868899929\` for \`638be6b\` **pending**. **No production deploy success was verified**. Re-check those runs and VPS HEAD/readiness before claiming deployed.
- \`HEXA_AUTO_DEPLOY\` repository variable was deliberately set to \`false\` earlier; current value could not be read through the available GitHub connector. **Do not assume the current value**. Workflow requires exact string \`true\` at a post-test release gate before SSH deployment. Do not change gate casually without user consent.
- Production \`bayer\` old known baseline was \`58c3074c6a095c23cee6a6691271ca7241146393\`; code may have been promoted on GitHub since. Actual VPS HEAD has not been reconfirmed after promotion.
- User prefers **one small action at a time**, Syrian colloquial Arabic, simple VS Code PowerShell or SSH commands, ask for output, never rush or touch production without explicit approval.

## 1) Repo, worktrees, branch policy
- GitHub repo: \`majdba123/HEXA-StoryEngine\`. Main Windows working checkout, checked out as \`montage\`: \`C:\Users\INTEL CENTER\Documents\GitHub\HEXA-StoryEngine\`; venv \`.venv\`; PowerShell VS Code.
- Previously separate Windows worktree \`E:\HEXA-Admin\`, local branch \`feature/admin-dashboard\`; **remote deleted** after merge, but **do not assert local worktree/branch was deleted**. Check safely before deleting anything; it may contain worktree metadata or user data.
- Independent \`E:\hexa-vnext2-wt\`, branch \`cinematic/vnext2\`: do not touch. Production VPS uses \`bayer\`.
- The full admin feature was merged into \`montage\` by fast-forward at \`7e2987de8fd35e69b88f421ad6589ae53607bab0\` (original admin CI \`38861127236\`, success, ~10,120 tests reported). User's Windows \`montage\` was pulled. Subsequent auth seed and local start enhancements committed on \`montage\`: \`53982d7\` (new two-user seeding), \`e745f40d\` (test auto-redirect fix), \`f12c967\` (explicit local reset deletes instead of archives), \`638be6b\` (docs reset semantics). Full montage validation on latter succeeded.
- GitHub comparison from \`feature/admin-dashboard\` to \`montage\` showed admin branch fully contained in montage, no missing commits; eventually GitHub reported only \`montage\` and \`bayer\`, with identical SHA \`638be6b\`.
- **The handoff update itself should remain docs-only on \`montage\`; do not promote documentation updates to \`bayer\` just to equalize branch pointers.**

## 2) Implemented web admin product
Production-grade admin dashboard and user auth now in repository:
- SQLite-backed \`Identity\` with \`users\`, sessions, login attempts, audit; Argon2 hashing, session CSRF, login rate-limiting, admin/user RBAC, ownership isolation. New account \`USER\` first login requires changing temporary password.
- Admin can view users, create accounts, change roles/emails/passwords, activate/deactivate, soft-delete; cannot accidentally disable/demote final admin. Personal password change invalidates sessions.
- Admin overview, video/render job history (including failed jobs and validated package name), export inventory and versioned downloads/deletion. Deletion is guarded; no deleting exports actively downloaded or tied to active jobs. Retention and migration regressions covered.
- Frontend and backend: \`app/web/identity.py\`, \`app/web/server.py\`, \`app/web/admin_data.py\`, \`app/web/static/admin.js\`, templates/login/change-password, and tests. \`pyproject.toml\` dependency \`argon2-cffi>=23.1,<26\`.
- Existing \`HEXA_WEB_TOKEN\` login protocol replaced in new code by email/password; the old environment token should be removed only **after** successful new auth rollout, not while old code may still be serving.
- New seeding in \`Identity.bootstrap()\`: \`HEXA_ADMIN_EMAIL\`, \`HEXA_ADMIN_BOOTSTRAP_PASSWORD\` required **only on an empty identity users table**; optional \`HEXA_INITIAL_USER_EMAIL\` plus \`HEXA_INITIAL_USER_PASSWORD\` provision a standard \`USER\` atomically with ADMIN; validates both entries, different emails, password min 12 chars; does **not** overwrite/reset existing accounts on subsequent starts. A DB with users but no active admin fails closed (documented offline restore; no automatic recreation). Existing legacy job table is retained and migrated, NOT wiped in production.

## 3) Local Windows developer runtime
- First local login failed even though user table existed. Diagnosed using \`Test-Path '.hexa\montage-local\web\jobs.sqlite3'\` -> \`True\`. Read-only SQLite query (PowerShell-friendly quoting):
  \`python -c "import sqlite3; db=sqlite3.connect('file:.hexa/montage-local/web/jobs.sqlite3?mode=ro', uri=True); print(db.execute('SELECT email_normalized, role, is_active FROM users').fetchall()); db.close()"\`
  yielded \`[('local-admin@example.invalid', 'ADMIN', 1)]\`; prior password unknown, bootstrap does not reset it.
- Original PowerShell Python one-liner using single outer quotes failed with \`SyntaxError\` due to quote passing; fixed using double-quoted \`-c\` and single quotes inside Python.
- Added \`tools/start_local_montage.ps1\`: works **only on checked-out montage branch**, requires \`.venv\Scripts\python.exe\`, sets **absolute** project-local paths for \`HEXA_WEB_STORAGE\`, upload/work/output/export roots; port \`127.0.0.1:8788\`; starts \`python -m app.web\`. No MySQL, Docker, or other DB process.
- \`-Reset\` switch explicitly and permanently **deletes** only project \`.hexa\montage-local\` (local SQLite, uploads, work, outputs, exports), **does NOT archive**; refuses unsafe symlinks/reparse points and refuses reset if server on port 8788 listening. Does not delete any other workspace/VPS. User expressly requested deletion instead of archive; the older script version archived, but latest code deletes. Old \`.hexa\local-archives\` created by earlier execution, if any, are not implicitly deleted by reset.
- Local demo seed: ADMIN \`majd@gmail.com\`, USER \`majd1@gmail.com\`; same deliberately local-only 12+-character demonstration password is in the script \`password2026!\`. User originally requested literal \`password\`, rejected due to 12-char validator. **NEVER seed production with this demo password**. User may change passwords from dashboard; USER must change initial password before normal app access.
- First-time clean start in VS Code PowerShell after stopping old local server:
  \`git pull --ff-only origin montage\`
  \`powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\start_local_montage.ps1 -Reset\`
  Then \`http://127.0.0.1:8788/login\`; keep terminal open. User later reported local work was fine, without posting exhaustive test output.
- Normal recurring development start, preserving data:
  \`powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\start_local_montage.ps1\`
  Stop with Ctrl+C. **Never use \`-Reset\` routinely** (destructive). Git pulls only when appropriate, not blindly in presence of uncommitted work.

## 4) Production VPS as verified from USER terminal logs
- VPS Ubuntu, service \`hexa-storyengine.service\`; site \`https://studio.hexaterminal.com\`; deployed worktree \`/var/www/hexa-storyengine\`; service user \`hexa-studio\`.
- systemd \`ExecStart\` confirmed: \`/opt/hexa-render/venv/bin/python -m uvicorn app.web.server:app --host 127.0.0.1 --port 8787 --workers 1 --proxy-headers --forwarded-allow-ips 127.0.0.1\`. \`EnvironmentFiles=/etc/hexa-storyengine/hexa.env\` (loaded by systemd). Proxy HTTPS cookie forwarding still needs end-to-end verification after new auth rollout.
- ENV confirmed: \`HEXA_WEB_RETENTION_DAYS=7\`; \`HEXA_WORK_ROOT=/var/lib/hexa-storyengine/work\`; \`HEXA_EXPORT_ROOT=/var/lib/hexa-storyengine/exports\`; \`HEXA_WEB_STORAGE=/var/lib/hexa-storyengine/web\`. SQLite at \`/var/lib/hexa-storyengine/web/jobs.sqlite3\`.
- Prior idle result \`ACTIVE_OR_RECENT_UPLOADS = 0\`; dynamic; recheck before any deploy. Need ensure no active render too; deploy script checks readiness.
- Argon2 was initially missing \`ARGON2_INSTALLED = False\` in the **actual service venv**, then USER successfully installed \`argon2-cffi-25.1.0\`, bindings, cffi, pycparser with \`sudo /opt/hexa-render/venv/bin/python -m pip install 'argon2-cffi>=23.1,<26'\`. USER confirmed follow-up actual hash/verify test \`ARGON2_OK = True\`. No app restart was performed for that.
- Read-only production SQLite inspection: \`JOBS_TABLE = True\`, \`USERS_TABLE = False\`, \`DATABASE_INTEGRITY = ok\` BEFORE installing new web version. Absence of \`users\` is expected on old web version. **Do not reset/replace production DB**; new code creates auth tables in same SQLite.
- USER created DB-only hot backup with SQLite backup API, permissions mode 0600 at \`/root/hexa-backups/pre-admin-20261016-073448.sqlite3\`; reported \`SQLITE_BACKUP_OK = True\`. No full export/video copy (potentially huge). Deploy script also makes transactional SQLite backup and config backup.
- Read-only env keys: \`HEXA_ADMIN_EMAIL=NOT SET\`; \`HEXA_ADMIN_BOOTSTRAP_PASSWORD=NOT SET\`; \`HEXA_INITIAL_USER_EMAIL=NOT SET\`; \`HEXA_INITIAL_USER_PASSWORD=NOT SET\`; \`HEXA_WEB_ALLOWED_HOSTS=SET\`; \`HEXA_WEB_TOKEN=SET\`. This scan was **before** adding new account settings.
- Assistant supplied a root-run Python command to update \`/etc/hexa-storyengine/hexa.env\` atomically via temp file/permissions 0600. It generates **two separate strong random production passwords** via \`secrets.token_urlsafe(24)\` and adds:
  \`HEXA_ADMIN_EMAIL=majd@gmail.com\`
  \`HEXA_ADMIN_BOOTSTRAP_PASSWORD=<strong random, stored only on VPS>\`
  \`HEXA_INITIAL_USER_EMAIL=majd1@gmail.com\`
  \`HEXA_INITIAL_USER_PASSWORD=<different strong random, stored only on VPS>\`
  USER responded **"تم" (done)**. Do **not claim a machine-verified CONFIGURATION_OK output** because it was not pasted. Verify only PRESENCE/empty vs set (never secret contents) before deployment. User was instructed to save the displayed passwords personally and never paste them. They were not disclosed to assistant.
- \`HEXA_WEB_TOKEN\` was deliberately **not yet removed**, to avoid breaking old running web version. Remove after verified new auth.
- Status before this handoff: **no confirmed production restart, new user table, working live login, new renderer test, nor deployed SHA**. Deployment risk is real if CI is blocked or systemd start fails.

## 5) GitHub production pipeline / release risks
- Workflow \`.github/workflows/hexa-production-deploy.yml\` runs on pushes to \`bayer\` and workflow_dispatch; mandatory Python lint/compile, tests/web, tests/test1, tests/test2, tests/test3, certification, package holdouts, visual, **6 real package corpus Levels A-D**, checks latest bayer SHA, requires Actions variable \`HEXA_AUTO_DEPLOY == 'true'\`, then deploys over restricted SSH.
- VPS install script \`/usr/local/sbin/hexa-deploy\` (source version \`ops/deploy/hexa-deploy.sh\`) checks clean \`bayer\` worktree, active service, idle render/uploads, checks exact SHA, fast-forward only, SQLite/config backup, maintenance mode, stops service, \`git merge --ff-only\`, restarts service, readiness checks, and attempts code rollback on failure. **It does not install pip dependencies**. Argon2 specifically was installed manually before push. Do NOT modify deploy scripts/reboot unless required and approved.
- Earlier known \`HEXA_AUTO_DEPLOY=false\` could mean \`bayer\` CI finishes tests then BLOCKS intentional deploy. **Check current run and variable with safe commands/UI, never promise auto deployment without verification.**
- Critical nuance: GitHub repo/branch update now shows code already merged into \`bayer\` at \`638be6b\`; avoid offering repeat merge. Even if all unit suites pass, CI and actual VPS readiness/live-login still need proof. The live \`HEXA_WEB_TOKEN\` may still grant old behavior until cutover; do not remove until new auth works. Also validate Nginx/proxy secure cookies.
- Release validations after deploy: actual VPS \`git rev-parse HEAD\` equals certified \`bayer\` SHA; \`systemctl is-active hexa-storyengine.service\`; internal \`/ready\` ready=true; external \`https://studio.hexaterminal.com/login\` loads; login ADMIN and USER with their **distinct** production secrets; USER forced change password; admin dashboard loads; user management; existing jobs/history/exports still accessible to admin; upload and one controlled real FFmpeg Final Package render; ensure exports and prior project data preserved; no active uploads interrupted; check logs **without printing secrets**. Only delete obsolete HEXA_WEB_TOKEN and remove bootstrap passwords from root-only env **after account persistence and recovery method confirmed** (restart should not require them for existing accounts; prevent future unintended reuse).
- Production change guidance: do **not** edit/commit real env or secrets to GitHub, or dump production env in logs/chat. Verify file owner/mode, working directory, maintenance state, CI gate, and idle jobs. Never revert SQLite data by blindly restoring older backup; migrations + later jobs could be lost.
- \`docs/admin/production-activation.md\` and \`docs/admin/local-setup.md\` contain additional activation instructions.

## 6) Immediate next action for the successor (ONE STEP)
1. **Do not ask user to merge again.** First inspect GitHub run \`38868899929\` (\`bayer\` SHA \`638be6b\`), related run \`38868875613\`, and current Github branch refs. Determine latest tests status and if deploy blocked by \`HEXA_AUTO_DEPLOY\`; not visible from former connector query.
2. If deployment not confirmed, ask USER for **one read-only SSH check**, e.g.:
   \`cd /var/www/hexa-storyengine && git rev-parse --short HEAD && sudo systemctl is-active hexa-storyengine.service\`.
   User prefers running commands personally, in sequence, returning output. Check production env key presence without printing secrets as needed.
3. Proceed to the safest outstanding deployment validation/gate step with explicit user approval; no unrequested writes, no new seed reruns, no VPS destructive actions.
4. Check successful live login for both seeded production users, preservation of jobs/uploads/exports, and live role security after certified deploy. Plan account secret cleanup only after verified.
5. For local development, refer to the two PowerShell commands above; no routine reset.

## 7) Working practices and non-admin historical context
- User demands senior architecture/FFmpeg/CPU/memory/disk/GPU scrutiny, frame accuracy, synchronization, no changes to Composition without agreement, QA with numeric comparisons, and no regressions across six/seven packages. The project has long prior multi-sprint visual, motion, and alignment history in \`HEXA_PROJECT_CONTINUITY_SOURCE.md\`; do not overwrite historical decisions with this release-specific handoff.
- Protect \`bayer\` deployment and independent cinematic worktree. Avoid unnecessary abstractions, unexpected auto-reencoding, and tests that mutate user data. For this admin rollout, prioritize persistence, isolation, authentication, backward compatibility, and clear rollback/verification.
- Response language: colloquial Syrian Arabic; user frequently says "يا وحش"; concise, non-technical explanation; one command at a time and ask for output before next irreversible action.

## 8) Copy-paste next-chat prompt
> نحن نكمل مشروع HEXA StoryEngine. اقرأ أولًا \`HEXA_PROJECT_CONTINUITY_SOURCE.md\` وخصوصًا رابط الـHandoff الأحدث \`docs/handoffs/2026-10-16-admin-local-production-release.md\`. طبّق القرارات والـSHAs والقيود فيه؛ لا تعيد الشغل المنجز. أهم تحديث: وقت توثيقنا GitHub \`montage\` و\`bayer\` كانا متطابقين على \`638be6b\`، وبرانش الأدمن البعيد محذوف، لكن نشر VPS **غير مؤكّد** وكانت CI لـ\`bayer\` جارية. آخر تحقق من الإنتاج: Argon2 موجود وشغال، SQLite سليمة ونسختها الاحتياطية محفوظة، وأنا ضفت إعدادات الحسابين للإنتاج (ما ترجع تطلب أسرارهم ولا تعرض كلمات مرور). افحص حالة GitHub Actions الحالية ثم خذ مني تحقق SSH قراءة فقط حسب الحاجة، وكمّل نشر والتحقق من الأدمن بحذر، خطوة واحدة كل مرة. ممنوع حذف بيانات السيرفر، ممنوع المساس بعمل \`cinematic/vnext2\`، لا تعمل Merge جديد إذا الكود موجود أصلًا على \`bayer\`، ولا تعتبر CI نجاح نشر إلا بدليل.
